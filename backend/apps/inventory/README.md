# inventory

Stock receipts, movements, counts and adjustments.

Owns: StockReceipt, StockReceiptItem, StockMovement, StockCount, StockCountItem.
Depends on: `products`, `audit`.
The movement ledger is authoritative; a count records variance and never overwrites expected stock (spec §11.3, §12.2).
