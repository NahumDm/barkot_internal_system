# sales

Sales, sale items and payments.

Owns: Sale, SaleItem, Payment, transaction numbering.
Depends on: `products`, `inventory`, `finance`, `audit`.
A completed sale writes header, items, payment and stock movement in one transaction (spec §13.1).
