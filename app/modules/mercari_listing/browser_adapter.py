"""Mercari Shops form adapter. Editing autosaves; publishing stays manual."""
import json
import re
import unicodedata
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from app.image_assets import resolve_image_path
from app.listing_preparation import listing_requirements


SHOPS_SIGNIN = "https://mercari-shops.com/signin/seller"


def validate_shop_management_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "mercari-shops.com" or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("请填写 mercari-shops.com 的 https 管理页面链接")
    if not parsed.path.startswith("/seller/") and not parsed.path.startswith("/signin/seller"):
        raise ValueError("请填写店铺管理页面链接，不是买家商品页")
    return url


def is_signed_in(page: Page) -> bool:
    parsed = urlparse(page.url)
    if parsed.hostname != "mercari-shops.com" or not parsed.path.startswith("/seller/shops/"):
        return False
    try:
        title = page.title()
        if re.search(r"(?:ログイン|サインイン)\s*(?:ページ|画面)|ログインしてください|sign[\s-]?in(?:\s+page)?", title, re.I):
            return False
        login_controls = page.locator(
            'input[type="password"], form[action*="login"], '
            'form[action*="signin"], form[action*="sign-in"]'
        )
        return login_controls.count() == 0
    except Exception:
        # An unreadable or partially loaded page is not proof of authentication.
        return False


class ShopsBrowserAdapter:
    # Actual 2026-10 form labels do not point at the generated input IDs.
    # Names/test IDs are used first; exact labels retain compatibility with older forms.
    CONTROLS = {
        "title_ja": 'input[name="name"]', "description_ja": 'textarea[name="description"]',
        "price_jpy": 'input[name="price"]', "inventory_quantity": 'input[name="variants.0.quantity"]',
        "max_quantity_per_order": 'input[name="variants.0.maxQuantityPerOrder"]',
        "jan_code": 'input[name="variants.0.janCode"]', "management_code": 'input[name="variants.0.skuCode"]',
        "shipping_method": 'select[name="shippingMethodType.id"]',
        "shipping_payer": 'select[name="shippingPayerType.id"]',
        "shipping_origin": 'select[name="shippingFromState.id"]',
        "handling_days": 'select[name="shippingDurationType.id"]',
    }
    # Labels are matched exactly; ambiguous or changed controls are left for review.
    TEXT_FIELDS = {
        "title_ja": ("商品名", "商品名（必須）"),
        "description_ja": ("商品説明", "商品の説明", "商品情報"),
        "price_jpy": ("販売価格", "販売価格（円）", "販売価格（必須）", "価格"),
        "inventory_quantity": ("在庫数", "在庫数量", "在庫"),
        "jan_code": ("JANコード", "JAN コード"),
        "management_code": ("商品管理コード", "商品管理番号"),
        "max_quantity_per_order": ("1注文あたりの購入可能数",),
    }
    SELECT_FIELDS = {
        "category": ("カテゴリー", "カテゴリ", "カテゴリー（必須）"),
        "brand": ("ブランド",), "condition": ("商品の状態", "商品状態"),
        "shipping_method": ("配送方法", "配送の方法"), "shipping_payer": ("配送料の負担", "送料の負担"),
        "shipping_origin": ("発送元の地域", "発送元地域"), "handling_days": ("発送までの日数",),
    }

    def __init__(self, page: Page, checkpoint=lambda: None, expected_shop=""):
        self.page = page
        self.checkpoint = checkpoint
        self.expected_shop = expected_shop
        self.form_path = None
        self.product_draft_id = None

    def guard(self):
        self.checkpoint()
        if not is_signed_in(self.page):
            raise ValueError("请先登录并进入指定店铺管理页面")
        if self.expected_shop:
            from app.browser.shop_connection import belongs_to_shop
            if not belongs_to_shop(self.page.url, self.expected_shop):
                raise ValueError("当前页面已离开指定店铺，已停止填写")
        if self.form_path:
            url = urlparse(self.page.url)
            current_id = parse_qs(url.query).get("productDraftId", [None])[0]
            if url.path != self.form_path or (self.product_draft_id and current_id != self.product_draft_id):
                raise ValueError("商品页面发生切换，已停止填写或保存，请核对原草稿")
            if current_id:
                self.product_draft_id = current_id

    @staticmethod
    def normalized(value):
        return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value)))

    def field_control(self, field, labels=()):
        selector = self.CONTROLS.get(field)
        if selector:
            control = self.page.locator(selector)
            if control.count() == 1:
                return control
        return self.control(labels) if labels else None

    def inspect(self):
        self.guard()
        self.page.locator(self.CONTROLS["title_ja"]).wait_for(state="visible", timeout=15000)
        if self.page.get_by_role("dialog").count():
            raise ValueError("请先关闭店铺表单上的弹窗，再检查或填写")
        # Shipping controls hydrate after the title input; do not misclassify loading as a schema change.
        try:
            self.page.locator(self.CONTROLS["handling_days"]).wait_for(state="attached", timeout=15000)
        except PlaywrightTimeout:
            pass
        fields = []
        for field in listing_requirements()["required"]:
            key = field["field"]
            selector = {"image_asset_ids": 'input[type="file"][accept*="image"]',
                        "condition": '[data-testid="condition-select-box"]',
                        "category": '[data-testid="categories"]'}.get(key, self.CONTROLS.get(key))
            control = self.page.locator(selector)
            fields.append({**field, "recognized": control.count() == 1})
        return {"stage": "inspection", "fields": fields, "url": self.page.url,
                "requirements": listing_requirements(), "autosaves_on_edit": True,
                "category_fields_pending": True,
                "missing_controls": [f["label"] for f in fields if not f["recognized"]]}

    def inspect_category_fields(self):
        """Read category-dependent form controls after the category path is selected."""
        known_names = [
            "name", "description", "price", "variants.0.quantity",
            "variants.0.maxQuantityPerOrder", "variants.0.janCode", "variants.0.skuCode",
            "shippingMethodType.id", "shippingPayerType.id", "shippingFromState.id",
            "shippingDurationType.id", "preOrder.enabled",
        ]
        return self.page.evaluate(
            """(knownNames) => {
              const visible = el => {
                const style = getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' &&
                  style.opacity !== '0' && rect.width > 0 && rect.height > 0;
              };
              const contextText = el => {
                const wrapper = el.closest('label,fieldset,[data-testid*=field],[class*=Field],[class*=field]') || el.parentElement;
                return (wrapper?.innerText || '').replace(/\\s+/g, ' ').trim();
              };
              const labelText = el => {
                const labels = el.labels ? [...el.labels].map(label => {
                  const clone = label.cloneNode(true);
                  clone.querySelectorAll('input,select,textarea,button').forEach(control => control.remove());
                  return clone.innerText;
                }).join(' ') : '';
                return (labels || el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.name || el.id || '').replace(/\\s+/g, ' ').trim();
              };
              const controls = [...document.querySelectorAll('input,select,textarea,[role=combobox]')]
                .filter(el => visible(el) && !el.disabled && el.getAttribute('aria-disabled') !== 'true' && !el.closest('[role=dialog]'))
                .filter(el => !knownNames.includes(el.name || '') &&
                  !['hidden','file','submit','button','reset'].includes((el.type || '').toLowerCase()));
              const fields = [];
              const radioNames = new Set();
              const checkboxNames = new Set();
              for (const el of controls) {
                const type = (el.type || '').toLowerCase();
                if (type === 'checkbox' && el.name) {
                  if (checkboxNames.has(el.name)) continue;
                  checkboxNames.add(el.name);
                  const group = controls.filter(other => other.type === 'checkbox' && other.name === el.name);
                  if (group.length > 1) {
                    const context = group.map(contextText).join(' ');
                    fields.push({key: el.name, name: el.name, label: labelText(el) || el.name,
                      kind: 'checkbox_group', required: group.some(option => option.required || option.getAttribute('aria-required') === 'true') || /必須|required|\*/i.test(context),
                      multiple: true, options: group.map(option => ({value: option.value, label: labelText(option)}))});
                    continue;
                  }
                }
                if (type === 'radio' && el.name) {
                  if (radioNames.has(el.name)) continue;
                  radioNames.add(el.name);
                  const group = controls.filter(other => other.type === 'radio' && other.name === el.name);
                  const options = group.map(option => ({
                    value: option.value,
                    label: labelText(option),
                  }));
                  const context = group.map(contextText).join(' ');
                  fields.push({key: el.name, name: el.name, label: labelText(el) || el.name,
                    kind: 'radio', required: group.some(option => option.required || option.getAttribute('aria-required') === 'true') || /必須|required|\\*/i.test(context),
                    options});
                  continue;
                }
                const context = contextText(el);
                const options = el.tagName === 'SELECT'
                  ? [...el.options].filter(option => option.value !== '').map(option => ({value: option.value, label: option.textContent.trim()}))
                  : [];
                fields.push({key: el.name || el.id || labelText(el), name: el.name || '', id: el.id || '',
                  label: labelText(el) || el.name || el.id, kind: el.tagName === 'SELECT' ? 'select' : el.tagName === 'TEXTAREA' ? 'textarea' : el.getAttribute('role') === 'combobox' ? 'combobox' : type || el.tagName.toLowerCase(),
                  required: Boolean(el.required || el.getAttribute('aria-required') === 'true' || /必須|required|\\*/i.test(context)),
                  multiple: Boolean(el.multiple), options});
              }
              return fields;
            }""",
            known_names,
        )

    def fill_category_fields(self, draft: dict, report: dict) -> None:
        fields = self.inspect_category_fields()
        report["category_fields"] = fields
        provided = draft.get("category_attributes") or {}
        matched_keys = set()
        for field in fields:
            key = field.get("name") or field.get("id") or field.get("label")
            value_key = next((candidate for candidate in (field.get("name"), field.get("label"), field.get("key"))
                              if candidate and candidate in provided), None)
            value_record = provided.get(value_key) if value_key else None
            value = value_record.get("value") if isinstance(value_record, dict) else value_record
            evidence = ({key: value_record[key] for key in ("source", "evidence", "source_url") if value_record.get(key)}
                        if isinstance(value_record, dict) else {})
            if value_key:
                matched_keys.add(value_key)
            if value in (None, ""):
                message = {"field": key, "label": field.get("label") or key,
                           "required": field["required"], "options": field.get("options", []),
                           "reason": "分类已展开此商品属性；资料包中没有对应值"}
                if field["required"]:
                    field["status"] = "missing_required"
                    report["needs_manual"].append(message)
                else:
                    field["status"] = "missing_optional"
                    report["skipped_optional"].append(message)
                continue
            if not evidence.get("evidence") and not evidence.get("source_url"):
                field["status"] = "needs_manual"
                field["value"] = value
                field["evidence"] = evidence
                report["needs_manual"].append({"field": key, "label": field.get("label") or key,
                                               "required": field["required"], "value": value,
                                               "options": field.get("options", []), "evidence": evidence,
                                               "reason": "分类属性缺少来源原文或来源链接；为避免猜测，未填写"})
                continue
            try:
                name = field.get("name")
                selector = f'[name={json.dumps(name, ensure_ascii=False)}]' if name else ""
                control = self.page.locator(selector) if selector else self.page.get_by_label(field["label"], exact=True)
                kind = field["kind"]
                if kind == "checkbox_group":
                    if control.count() != len(field.get("options", [])):
                        raise ValueError("分类属性多选项数量发生变化")
                elif control.count() != 1:
                    raise ValueError("无法唯一定位分类属性控件")
                values = value if isinstance(value, list) else [value]
                if kind == "select":
                    if field.get("multiple"):
                        options = control.locator("option").evaluate_all("els=>els.map(el=>({value:el.value,label:el.textContent}))")
                        selected = []
                        for entry in values:
                            matches = [option for option in options if self.normalized(option["label"]) == self.normalized(entry) or option["value"] == str(entry)]
                            if len(matches) != 1:
                                raise ValueError("分类属性选项没有唯一匹配")
                            selected.append(matches[0]["value"])
                        control.select_option(selected, timeout=5000)
                    else:
                        self.choose_native(control, values[0])
                elif kind == "radio":
                    option_values = [option["value"] for option in field.get("options", [])
                                     if self.normalized(option["label"]) == self.normalized(values[0]) or option["value"] == str(values[0])]
                    if len(option_values) != 1:
                        raise ValueError("分类属性单选项没有唯一匹配")
                    radio = self.page.locator(f'[type="radio"][name={json.dumps(name, ensure_ascii=False)}][value={json.dumps(option_values[0], ensure_ascii=False)}]')
                    radio.check(timeout=5000)
                elif kind == "checkbox_group":
                    if not isinstance(value, list):
                        raise ValueError("分类属性多选框需要明确的数组值")
                    selected_values = set()
                    for entry in value:
                        matches = [option["value"] for option in field["options"]
                                   if self.normalized(option["label"]) == self.normalized(entry) or option["value"] == str(entry)]
                        if len(matches) != 1:
                            raise ValueError("分类属性多选项没有唯一匹配")
                        selected_values.add(matches[0])
                    for index, option in enumerate(field["options"]):
                        control.nth(index).set_checked(option["value"] in selected_values, timeout=5000)
                elif kind == "checkbox":
                    if not isinstance(value, bool):
                        raise ValueError("分类属性复选框需要明确的布尔值")
                    control.set_checked(value, timeout=5000)
                elif kind in ("text", "number", "date", "textarea"):
                    control.fill(str(values[0]), timeout=5000)
                else:
                    raise ValueError("平台分类属性控件类型暂不支持自动填写")
                field["status"] = "filled"
                field["value"] = value
                field["evidence"] = evidence
                report["filled"].append(f"分类属性：{field.get('label') or key}")
            except (PlaywrightTimeout, ValueError) as error:
                field["status"] = "needs_manual"
                field["value"] = value
                field["evidence"] = evidence
                report["needs_manual"].append({"field": key, "label": field.get("label") or key,
                                               "required": field["required"], "value": value,
                                               "options": field.get("options", []), "evidence": evidence,
                                               "reason": str(error)})
        for key, value in provided.items():
            if key in matched_keys:
                continue
            report["needs_manual"].append({"field": key, "label": key, "value": value,
                                           "reason": "资料包中有分类属性，但当前店铺分类下没有对应控件"})

    def choose_native(self, control, value):
        options = control.locator("option").evaluate_all("els=>els.map(el=>({value:el.value,label:el.textContent}))")
        matches = [o for o in options if self.normalized(o["label"]) == self.normalized(value) or o["value"] == str(value)]
        if len(matches) != 1:
            raise ValueError("没有唯一且相同的平台选项")
        option = matches[0]
        if control.input_value() == option["value"]:
            return
        if control.is_disabled():
            raise ValueError("平台锁定了不同的选项，请人工核对配送配置")
        control.select_option(value=option["value"], timeout=5000)
        if control.input_value() != option["value"]:
            raise ValueError("平台选项与预期不一致")

    def choose_popup(self, field, value):
        trigger = self.page.get_by_test_id("condition-select-box" if field == "condition" else "categories")
        if trigger.count() != 1:
            raise ValueError("没有识别到选择弹窗")
        # Autosave toasts can stack over the modal trigger and intercept clicks.
        try:
            self.page.add_style_tag(content=".Toastify__toast-container,.Toastify__toast{pointer-events:none!important}")
        except Exception:
            pass
        dialog = self.page.get_by_role("dialog")
        if dialog.count() and dialog.is_visible():
            trigger.dispatch_event("click")
            dialog.wait_for(state="hidden", timeout=5000)
        trigger.dispatch_event("click")
        try:
            parts = [str(value)] if field == "condition" else re.split(r"\s*[>＞/]\s*", str(value))
            dialog.wait_for(state="visible", timeout=5000)
            for index, part in enumerate(parts):
                self.guard()
                option = dialog.get_by_role("listitem").filter(has=self.page.get_by_text(part, exact=True))
                # Category list items contain text directly, condition items contain paragraphs.
                if option.count() == 0:
                    option = dialog.get_by_role("listitem").filter(has_text=re.compile(r"^" + re.escape(part) + r"$"))
                option.wait_for(state="visible", timeout=8000)
                if option.count() != 1:
                    raise ValueError(f"分类路径或成色选项不唯一：{part}")
                # Shops animates nested category rows continuously while switching levels.
                # A normal Playwright click can time out waiting for the row to become stable;
                # the exact, unique list item is still verified and the next level is checked.
                # Dispatch on the verified row instead of clicking coordinates: the
                # nested list animates and can otherwise send a forced mouse click to
                # the neighboring category while its bounding box is moving.
                option.dispatch_event("click")
                if index < len(parts) - 1:
                    next_option = dialog.get_by_role("listitem").filter(
                        has=self.page.get_by_text(parts[index + 1], exact=True)
                    )
                    next_option.wait_for(state="visible", timeout=8000)
                    if next_option.count() != 1:
                        raise ValueError(f"分类路径不唯一：{parts[index + 1]}")
            trigger_test_id = "condition-select-box" if field == "condition" else "categories"
            self.page.wait_for_function(
                """({leaf,testId})=>{const d=document.querySelector('[role="dialog"]');
                   const c=document.querySelector(`[data-testid="${testId}"]`);
                   return (!d || !d.getClientRects().length) && c &&
                     c.innerText.normalize('NFKC').replace(/\\s/g,'').includes(leaf.normalize('NFKC').replace(/\\s/g,''));}""",
                arg={"leaf": parts[-1], "testId": trigger_test_id}, timeout=12000,
            )
            if self.normalized(parts[-1]) not in self.normalized(trigger.inner_text()):
                raise ValueError("选择结果与预期不一致")
        finally:
            self.guard()
            if dialog.count() and dialog.is_visible():
                # The live Shops modal does not consistently close on Escape.
                trigger.dispatch_event("click")
                dialog.wait_for(state="hidden", timeout=5000)

    def control(self, labels):
        for label in labels:
            control = self.page.get_by_label(label, exact=True)
            if control.count() == 1:
                return control
        return None

    def fill(self, draft: dict, image_records: list[dict]) -> dict:
        self.guard()
        if self.field_control("title_ja", self.TEXT_FIELDS["title_ja"]) is None or self.field_control("price_jpy", self.TEXT_FIELDS["price_jpy"]) is None:
            raise ValueError("请打开新增商品页面；必须识别到唯一的商品名和销售价格输入框后才会填写")
        report = {"stage": "after_fill", "filled": [], "needs_manual": [], "skipped_optional": [],
                  "saved": False, "url": self.page.url, "autosaves_on_edit": True}
        if draft.get("reservation_sale") or draft.get("multi_variant"):
            raise ValueError("预约或多规格商品需要在店铺人工设置；请先使用普通销售、单规格资料")
        preorder = self.page.locator('input[name="preOrder.enabled"]')
        if preorder.count() and preorder.is_checked():
            raise ValueError("当前表单启用了预约销售，请使用新的普通销售表单")
        title_control = self.field_control("title_ja", self.TEXT_FIELDS["title_ja"])
        description = self.field_control("description_ja", self.TEXT_FIELDS["description_ja"])
        for field, labels in self.TEXT_FIELDS.items():
            value = draft.get(field)
            control = self.field_control(field, labels)
            if not value or control is None:
                continue
            current = control.input_value()
            matches = (re.sub(r"\D", "", current) == str(value)
                       if field == "price_jpy" else current == str(value))
            if current and not matches:
                raise ValueError("当前表单已有不同的商品资料；为避免覆盖，请核对原草稿")
        self.form_path = urlparse(self.page.url).path
        self.product_draft_id = parse_qs(urlparse(self.page.url).query).get("productDraftId", [None])[0]
        for field, labels in self.TEXT_FIELDS.items():
            self.guard()
            value = draft.get(field)
            if value in (None, ""):
                continue
            control = self.field_control(field, labels)
            if control is None:
                report["needs_manual"].append({"field": field, "label": labels[0], "reason": "未找到唯一对应输入框"})
                continue
            try:
                actual = control.input_value()
                matches = (re.sub(r"\D", "", actual) == str(value)
                           if field == "price_jpy" else actual == str(value))
                if not matches:
                    control.fill(str(value), timeout=5000)
                    actual = control.input_value()
                    if (re.sub(r"\D", "", actual) != str(value) if field == "price_jpy" else actual != str(value)):
                        raise ValueError("输入值与预期不一致")
                report["filled"].append(labels[0])
            except (PlaywrightTimeout, ValueError):
                report["needs_manual"].append({"field": field, "label": labels[0], "reason": "该字段需要人工核对"})
        for field, labels in self.SELECT_FIELDS.items():
            self.guard()
            value = draft.get(field)
            if not value:
                continue
            if field == "brand":
                report["skipped_optional"].append({"field": field, "label": labels[0], "value": value,
                                                    "reason": "店铺未提供可唯一匹配的品牌选项；品牌为可选项，保持未选"})
                continue
            if field in ("category", "condition"):
                try:
                    self.choose_popup(field, value)
                    report["filled"].append(labels[0])
                except (PlaywrightTimeout, ValueError) as error:
                    report["needs_manual"].append({"field": field, "label": labels[0], "value": value, "reason": str(error)})
                continue
            control = self.field_control(field, labels)
            if control is None or control.evaluate("el=>el.tagName") != "SELECT":
                report["needs_manual"].append({"field": field, "label": labels[0], "value": value, "reason": "请在店铺对应选项中确认"})
                continue
            try:
                self.choose_native(control, value)
                report["filled"].append(labels[0])
            except (PlaywrightTimeout, ValueError):
                report["needs_manual"].append({"field": field, "label": labels[0], "value": value, "reason": "没有完全相同的选项"})
        # Shops reveals additional category-dependent fields only after the final
        # category is selected. Read them at that point instead of assuming one
        # universal product schema.
        self.fill_category_fields(draft, report)
        paths = []
        for image in image_records:
            path = resolve_image_path(image["listing_path"])
            if path:
                paths.append(str(path))
        uploader = self.page.locator('input[type="file"][accept*="image"]')
        self.guard()
        if paths and uploader.count() == 1:
            try:
                if len(paths) > 1 and uploader.get_attribute("multiple") is None:
                    raise ValueError("图片位只接受单张，需要人工逐张添加")
                expected_names = [path.replace("\\", "/").rsplit("/", 1)[-1] for path in paths]
                existing_names = uploader.evaluate("el=>Array.from(el.files || []).map(file=>file.name)")
                if existing_names != expected_names:
                    uploader.set_input_files(paths, timeout=15000)
                report["filled"].append(f"商品图片（{len(paths)} 张）")
            except (PlaywrightTimeout, ValueError) as error:
                report["needs_manual"].append({"field": "images", "reason": str(error)})
        else:
            report["needs_manual"].append({"field": "images", "reason": "请在店铺页面检查并添加商品图片"})
        if not report["filled"]:
            raise ValueError("当前页面没有识别到可填写的商品表单。请打开店铺的新增商品页面后重新执行。")
        self.guard()
        report["url"] = self.page.url
        return report

    def save_reviewed_draft(self) -> dict:
        self.guard()
        save = self.page.get_by_role("button", name=re.compile(r"^(?:下書き保存|下書きに保存|下書きとして保存|下書きを保存|下書きへ保存する)$"))
        if save.count() != 1:
            raise ValueError("无法唯一识别“保存为草稿”按钮，请在浏览器中手动保存；系统不会点击公开按钮")
        before = self.page.url
        title = self.field_control("title_ja", self.TEXT_FIELDS["title_ja"]).input_value()
        before_body = self.page.locator("body").inner_text()
        success_pattern = re.compile(r"下書き.{0,20}保存.{0,20}(?:しました|されました|完了)")
        before_success_count = len(success_pattern.findall(before_body))
        save.click(timeout=8000)
        try:
            self.page.wait_for_function(
                """({beforeUrl,title,beforeSuccessCount})=>{
                  const text=document.body.innerText;
                  const draftList=location.pathname.endsWith('/products') &&
                    new URLSearchParams(location.search).get('tab')==='draft' && text.includes(title);
                  const successes=[...text.matchAll(/下書き.{0,20}保存.{0,20}(しました|されました|完了)/g)].length;
                  return draftList || successes>beforeSuccessCount || (location.href!==beforeUrl && text.includes(title));
                }""",
                arg={"beforeUrl": before, "title": title, "beforeSuccessCount": before_success_count},
                timeout=20000,
            )
        except PlaywrightTimeout as error:
            raise ValueError("已点击草稿保存，但页面未显示成功确认。请人工核对店铺，避免重复创建。") from error
        return {"saved": True, "url": self.page.url, "published": False}

    def read_orders(self) -> list[dict]:
        self.guard()
        self.page.wait_for_function("""()=>document.querySelector('table tbody a[href*="/orders/"],table tbody a[href*="/order-transactions/"]') || [...document.querySelectorAll('p')].some(el=>el.textContent==='注文はありません')""", timeout=15000)
        # Only order/product fields are returned; buyer names, addresses and phone numbers are excluded.
        rows = self.page.locator('table tbody a[href*="/orders/"],table tbody a[href*="/order-transactions/"]').evaluate_all(r"""links=>links.slice(0,100).map(link=>{
          if(['upload','export','download','new','create'].includes(new URL(link.href).pathname.split('/').filter(Boolean).at(-1)))return null;
          const row=link.closest('tr');
          if(!row)return null;
          const text=row?.innerText||'';
          if(text.length>3000)return null;
          const order=text.match(/(?:注文番号|注文ID|取引ID)\s*[:：]?\s*([A-Za-z0-9_-]+)/);
          const number=order?.[1]||new URL(link.href).pathname.split('/').filter(Boolean).at(-1);
          const products=[...row.querySelectorAll('a[href*="/products/"]')];
          const quantity=text.match(/数量\s*[:：]?\s*(\d+)/);
          const amount=text.match(/(?:商品代金|商品小計|商品金額)\s*[:：]?\s*[¥￥]?\s*([\d,]+)/);
          return {external_order_id:number,order_url:link.href,
            external_product_url:products.length===1?products[0].href:'',
            title:products.length===1?products[0].textContent.trim():link.textContent.trim(),
            quantity:quantity?Number(quantity[1]):0,amount_jpy:amount?Number(amount[1].replaceAll(',','')):null,
            needs_review:products.length!==1||!quantity||!amount};
        }).filter(Boolean)""")
        unique = {}
        for row in rows:
            if not row["external_order_id"] or len(row["external_order_id"]) > 200:
                continue
            row["title"] = row["title"][:500]
            unique[(row["external_order_id"], row["external_product_url"])] = row
        if not unique:
            if self.page.get_by_role("heading", name="注文一覧", exact=True).count() and self.page.get_by_text("注文はありません", exact=True).count():
                return []
            raise ValueError("当前页面没有识别到订单行。请打开订单列表；若页面结构已变化，需要按实际页面更新适配器。")
        return list(unique.values())
