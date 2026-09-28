# inventory

Products, stock receiving, stock counts, movements and breakage/waste.

Primary operator for receiving is the Barman; counting is role-flexible across Cashier, Manager and Owner.
Stock count keeps Expected, Physical Count and Variance visually distinct and never rewrites expected stock (spec §12.2).
Breakage/waste creates a recorded stock-out movement with a reason, never a direct balance edit.
