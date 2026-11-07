# Usage Thresholds: Alert Rules

| Rule | Condition | Action | Notes |
|---|---|---|---|
| Event window | Count feature_use events only | Look back 14 days from today | Only feature_use, not login or other |
| Trial detection | Customer has trial tag | Use trial thresholds from ws_thresholds | All others use standard thresholds |
| Onboarding policy | See ws_onboarding_policy worksheet | Apply onboarding exclusion rules from separate sheet | Moved to dedicated worksheet for clarity |
| Tag assignment | Each non-excluded customer | Tag as low-usage, normal-usage, or high-usage | Based on feature_use count vs thresholds |
| Low usage alert | Customer classified as low-usage | Send email + create Salesforce task | SF task subject must contain customer name |
| No alert for non-low | normal-usage or high-usage | Tag only, no email, no SF task | Only low-usage triggers alerts |
