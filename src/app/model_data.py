# model_data.py

MODEL_DEFINITIONS = {
  "invoice": [
    {"display": "発行日", "value": "issue_date"}, {"display": "利用月", "value": "issue_month"},
    {"display": "請求書番号", "value": "invoice_number"}, {"display": "タイトル", "value": "title"},
    {"display": "ページ番号", "value": "page_number"}, {"display": "請求元会社名", "value": "biller_company"},
    {"display": "請求元住所", "value": "biller_address"}, {"display": "登録番号", "value": "register_no"},
    {"display": "請求元TEL", "value": "biller_tel"}, {"display": "請求元FAX", "value": "biller_fax"},
    {"display": "請求先会社名", "value": "billing_company"}, {"display": "請求先部署名", "value": "office_name"},
    {"display": "通貨", "value": "currency"}, {"display": "合計金額税抜", "value": "subtotal"},
    {"display": "8%対象合計額", "value": "reduced_subtotal"}, {"display": "10%対象合計額", "value": "non_reduced_subtotal"},
    {"display": "合計金額税込", "value": "total_amount"}, {"display": "消費税", "value": "consumption_tax"},
    {"display": "税額10%", "value": "non_reduced_tax"}, {"display": "税額8%", "value": "reduced_tax"},
    {"display": "支払期限", "value": "due_date"}, {"display": "銀行名", "value": "bank_name"},
    {"display": "支店名", "value": "bankbranch_name"}, {"display": "口座種別", "value": "account_type"},
    {"display": "口座番号", "value": "account_number"}, {"display": "口座名義", "value": "account_name"}
  ],
  "receipt": [
    {"display": "タイトル", "value": "title"}, {"display": "発行日", "value": "issue_date"},
    {"display": "発行時刻", "value": "issue_time"}, {"display": "合計金額税込", "value": "total_amount"},
    {"display": "合計金額税抜", "value": "subtotal"}, {"display": "消費税", "value": "consumption_tax"},
    {"display": "税額10%", "value": "non_reduced_tax"}, {"display": "税額8%", "value": "reduced_tax"},
    {"display": "支払者会社名", "value": "billing_company"}, {"display": "支払者部署名", "value": "office_name"},
    {"display": "発行者会社名", "value": "biller_company"}, {"display": "発行者TEL", "value": "biller_tel"},
    {"display": "発行者住所", "value": "biller_address"}, {"display": "発行者部署名", "value": "biller_office_name"}
  ],
  "purchase_order": [
    {"display": "注文先会社名", "value": "seller_company"}, {"display": "注文先部署名", "value": "seller_division"},
    {"display": "注文先担当者名", "value": "seller_name"}, {"display": "注文書番号", "value": "buyer_ordernumber"},
    {"display": "注文日", "value": "buyer_date"}, {"display": "発行元会社名", "value": "buyer_company"},
    {"display": "発行元部署名", "value": "buyer_division"}, {"display": "発行元住所", "value": "buyer_address"},
    {"display": "発行元電話番号", "value": "buyer_phonenumber"}, {"display": "発行元FAX番号", "value": "buyer_faxnumber"},
    {"display": "発行元担当者名", "value": "buyer_name"}, {"display": "合計金額", "value": "buyer_totalamount"},
    {"display": "備考", "value": "remarks"}, {"display": "希望納期", "value": "receiver_deliverydate"},
    {"display": "納品先住所", "value": "receiver_address"}, {"display": "納品先電話番号", "value": "receiver_phonenumber"},
    {"display": "納品先FAX番号", "value": "receiver_faxnumber"}, {"display": "納品先担当者名", "value": "receiver_name"}
  ],
  "resident_card": [
    {"display": "氏名", "value": "name"}, {"display": "出生の年月日", "value": "birth_date"},
    {"display": "性別", "value": "sex"}, {"display": "住所", "value": "address"},
    {"display": "住民となった年月日", "value": "resident_date"}, {"display": "前住所", "value": "previous_address"},
    {"display": "世帯主氏名", "value": "householder_name"}, {"display": "続柄", "value": "relationship"}
  ],
  "salary_r3": [
    {"display": "支払を受ける者 住所又は居所", "value": "address"}, {"display": "支払を受ける者 氏名", "value": "name"},
    {"display": "支払金額", "value": "total_payment_amount"}, {"display": "給与所得控除後の金額", "value": "post_deduction_payment_amount"},
    {"display": "所得控除の額の合計額", "value": "total_deduction_amount"}, {"display": "源泉徴収税額", "value": "withholding_tax_amount"},
    {"display": "住宅借入金等特別控除の額", "value": "housing_loan_deduction_amount"}, {"display": "摘要", "value": "remarks"},
    {"display": "支払者 住所(所在地)", "value": "biller_address"}, {"display": "支払者 氏名(名称)", "value": "biller_name"}
  ],
  "automobile_tax": [
    {"display": "都道府県", "value": "prefecture"}, {"display": "年度", "value": "fiscal_year"},
    {"display": "証明書番号", "value": "certificate_number"}, {"display": "登録番号", "value": "license_plate"},
    {"display": "有効期限", "value": "expiration_date"}, {"display": "納税者氏名", "value": "taxpayer_name"}
  ],
  "medical_receipt": [
    {"display": "患者氏名", "value": "patient_name"}, {"display": "領収書番号", "value": "receipt_number"},
    {"display": "発行日", "value": "issue_date"}, {"display": "医療機関名", "value": "medical_institution_name"},
    {"display": "合計金額", "value": "total_amount"}, {"display": "負担率", "value": "copayment_rate"}
  ],
  "lease_contract": [
    {"display": "物件名称", "value": "property_name"}, {"display": "物件所在地", "value": "property_address"},
    {"display": "契約開始日", "value": "contract_start_date"}, {"display": "契約終了日", "value": "contract_end_date"},
    {"display": "契約日", "value": "contract_date"}, {"display": "貸主氏名", "value": "lessor_name"},
    {"display": "貸主住所", "value": "lessor_address"}, {"display": "借主氏名", "value": "lessee_name"},
    {"display": "借主住所", "value": "lessee_address"}
  ],
  "health_certificate": [
    {"display": "氏名", "value": "name"}, {"display": "生年月日", "value": "date_of_birth"},
    {"display": "年齢", "value": "age"}, {"display": "性別", "value": "sex"},
    {"display": "受診日", "value": "examination_date"}, {"display": "医療機関名", "value": "institution_name"},
    {"display": "総合判定", "value": "overall_judgment"}
  ],
  "resume": [
    {"display": "氏名", "value": "name"}, {"display": "生年月日", "value": "date_of_birth"},
    {"display": "性別", "value": "sex"}, {"display": "住所", "value": "address"},
    {"display": "電話番号", "value": "phone_number"}, {"display": "メールアドレス", "value": "email_address"}
  ],
  "life_insurance": [
    {"display": "証券番号", "value": "policy_number"}, {"display": "保険契約者", "value": "policyholder_name"},
    {"display": "被保険者", "value": "insured_name"}
  ],
  "payment": [
    {"display": "納付者氏名", "value": "payer_name"}, {"display": "納付者住所", "value": "payer_address"},
    {"display": "年度", "value": "fiscal_year"}, {"display": "期別", "value": "period"},
    {"display": "納期限", "value": "payment_deadline"}, {"display": "合計金額", "value": "total_amount"}
  ],
  "thai_invoice": [
    {"display": "会社名", "value": "biller_company"}, {"display": "税務番号", "value": "biller_tax_id"},
    {"display": "住所", "value": "biller_address"}, {"display": "電話番号", "value": "biller_tel"},
    {"display": "請求書番号", "value": "invoice_number"}, {"display": "発行日", "value": "issue_date"},
    {"display": "合計金額", "value": "total_amount"}
  ],
  "idcard": [
    {"display": "運転免許証/氏名", "value": "driver_license/name"}, {"display": "運転免許証/生年月日", "value": "driver_license/date_of_birth"},
    {"display": "運転免許証/住所", "value": "driver_license/address"}, {"display": "運転免許証/有効期限", "value": "driver_license/expiration_date"},
    {"display": "運転免許証/免許の条件等", "value": "driver_license/limitation"}, {"display": "運転免許証/免許証番号", "value": "driver_license/driver_number"},
    {"display": "運転免許証/住所変更(裏面)", "value": "driver_license/description"}, {"display": "マイナンバーカード/氏名", "value": "my_number/name"},
    {"display": "マイナンバーカード/住所", "value": "my_number/address"}, {"display": "マイナンバーカード/生年月日", "value": "my_number/date_of_birth"},
    {"display": "マイナンバーカード/有効期限", "value": "my_number/expiration_date"}, {"display": "マイナンバーカード/住所変更", "value": "my_number/description"},
    {"display": "マイナンバーカード/個人番号(裏面)", "value": "my_number/my_number"}, {"display": "健康保険証/保険証名", "value": "health_insurance/insurance_card_name"},
    {"display": "健康保険証/区分", "value": "health_insurance/section"}
  ]
}