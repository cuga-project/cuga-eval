# Data Quality: Quality Rules

| Rule ID | Condition | Required Field | Description |
|---|---|---|---|
| QR-01 | priority=high OR priority=urgent | organization_id | High/urgent tickets must have an organization |
| QR-02 | status=open | tags | Open tickets must have at least one tag |
