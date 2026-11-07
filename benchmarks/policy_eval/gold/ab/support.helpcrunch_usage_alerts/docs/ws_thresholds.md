# Usage Thresholds: Thresholds

| Customer Type | Low Max | Normal Max | Description | Notes |
|---|---|---|---|---|
| standard | 2 | 4 | Standard: <=2 low, 3-4 normal, 5+ high | Customers from 'OldCo' domain are exempt from email alerts and Salesforce task creation per exec override. Tag still applies. |
| trial | 0 | 1 | Trial: 0 low, 1 normal, 2+ high | Customers with company name containing 'Beta' are in a partner program -- classify using standard thresholds even if tagged trial |
