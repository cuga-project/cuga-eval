# Invoice Sending Rules

Before sending invoices:

1. Only send invoices with status AUTHORISED
2. Do NOT send invoices that have already been marked as SentToContact
3. Invoices with 'HOLD' in the reference field must NOT be sent
4. For invoices over $25,000 - CC the CFO at cfo@company.example.com

- Controller
