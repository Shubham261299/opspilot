# Sharma Traders — sample data (fictional)

Every name, number, phone and email here is invented, for the OpsPilot demo only.
"Today" in the data is **24 Sep 2026**. Regenerate everything with `python gen_data.py` (fixed seed, same output).

| File | What it is | Deliberate mess |
|---|---|---|
| `stock_register.xlsx` | Godown stock count, 60 items | Title rows above the header, a section-header row mid-table, a totals footer, mixed units (pcs/NOS/Coil), qty as text ("54 pcs"), a negative qty, blank rates, a blank item code, a duplicate row with a different count, a supplier short name, a discontinued item not in the master, and an open PO mentioned only in Remarks |
| `product_master.csv` | Clean catalogue with `aliases` (how customers actually write product names) | None; this is your reference for matching |
| `suppliers.csv` | 6 suppliers with lead times and payment terms | None |
| `customers.xlsx` | 25 shop-owner customers with credit limits and credit days | 4 phone formats, one duplicate shop with no code |
| `outstanding_dues.xlsx` | Unpaid customer bills | Customers referenced by shop name (not code), dates mixed between real dates and text |
| `sales_history_90d.csv` | 90 days of sales lines (~8,300 rows) | Clean; used for average daily demand |
| `whatsapp_orders_export.txt` | 3 days of WhatsApp chat, exported the way WhatsApp exports it | Hinglish, multi-line messages, quantity corrections in later messages, an order split across messages, a photo reference, enquiries mixed with orders, an unstocked product, and one abnormally large order |
| `invoice_*.pdf` | 4 supplier tax invoices | One has a 32% price jump; one is a duplicate of another |
| `company_policy.pdf` | Reorder rules, credit rules, order and invoice checks | The rules your agents must follow (and cite, from v0.4) |
| `answer_key.json` | What a correct system should output | Use it for tests and evals from week 7. **Don't show it to the LLM.** |

## What's in the answer key

- `expected_reorders`: 8 products that should be reordered, with the exact quantity from the policy formula. One low item is deliberately **not** in the list because stock is already on order.
- `expected_payment_actions`: 10 customers, with `SEND_REMINDER` or `HOLD_NEW_ORDERS`.
- `expected_orders`: 16 orders the WhatsApp parser should produce (after applying corrections), plus 4 messages that are **not** orders.
- `anomalies`: 3 (abnormal order size, invoice price jump, duplicate invoice).
- `data_issues`: 15 planted data problems the intake should report.
