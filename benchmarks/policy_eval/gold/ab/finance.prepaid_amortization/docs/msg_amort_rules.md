# Prepaid Amortization Rules

Amortization rules:

1. Monthly amount = Total Prepaid / Term in Months
2. Only amortize items where the current date falls within the coverage period
3. Items that haven't started yet (Start Date > current month): skip
4. Items fully amortized (Remaining = $0): skip
5. Round to nearest cent
6. Report: Debit Expense Account, Credit Prepaid Asset

- Controller
