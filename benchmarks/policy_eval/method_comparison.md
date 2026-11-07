# Method comparison (check set from the tuning policies)

| Type | Method | Cases | Recall | False deny | p50 ms | $/check | Errors |
|---|---|---|---|---|---|---|---|
| allowed_values | code | 68 | 0.97 | 0.0% | 0 | 0.00000 | 0 |
| allowed_values | aws/gpt-oss-120b | 68 | 1.00 | 0.0% | 1421 | 0.00096 | 0 |
| allowed_values | openrouter:openai/gpt-oss-20b | 68 | 0.94 | 0.0% | 2121 | 0.00016 | 0 |
| allowed_values | openrouter:openai/gpt-oss-safeguard-20b | 68 | 0.76 | 0.0% | 1098 | 0.00054 | 3 |
| allowed_values | kev | 68 | 0.15 | 0.0% | 680 | 0.00001 | 0 |
| allowed_values | gcp/gemini-3.8-flash | 68 | 1.00 | 0.0% | 3390 | 0.00712 | 0 |
| approval | aws/gpt-oss-120b | 4 | 1.00 | 0.0% | 2053 | 0.00141 | 0 |
| approval | openrouter:openai/gpt-oss-20b | 4 | 1.00 | 0.0% | 1059 | 0.00009 | 0 |
| approval | openrouter:openai/gpt-oss-safeguard-20b | 4 | 1.00 | 0.0% | 563 | 0.00034 | 0 |
| approval | kev | 4 | 0.00 | 0.0% | 656 | 0.00001 | 0 |
| approval | gcp/gemini-3.8-flash | 4 | 0.50 | 0.0% | 4959 | 0.01060 | 0 |
| deadline | aws/gpt-oss-120b | 8 | 0.50 | 0.0% | 1828 | 0.00112 | 0 |
| deadline | openrouter:openai/gpt-oss-20b | 8 | 0.50 | 0.0% | 3425 | 0.00013 | 0 |
| deadline | openrouter:openai/gpt-oss-safeguard-20b | 8 | 0.50 | 25.0% | 1775 | 0.00065 | 0 |
| deadline | kev | 8 | 0.00 | 0.0% | 515 | 0.00001 | 0 |
| deadline | gcp/gemini-3.8-flash | 8 | 1.00 | 0.0% | 5718 | 0.01123 | 0 |
| definition | aws/gpt-oss-120b | 8 | 1.00 | 0.0% | 1931 | 0.00122 | 0 |
| definition | openrouter:openai/gpt-oss-20b | 8 | 0.75 | 0.0% | 1574 | 0.00013 | 0 |
| definition | openrouter:openai/gpt-oss-safeguard-20b | 8 | 0.75 | 0.0% | 1256 | 0.00073 | 1 |
| definition | kev | 8 | 0.00 | 0.0% | 598 | 0.00001 | 0 |
| definition | gcp/gemini-3.8-flash | 8 | 0.75 | 25.0% | 4448 | 0.00638 | 0 |
| derived_value | code | 8 | 1.00 | 0.0% | 0 | 0.00000 | 0 |
| derived_value | aws/gpt-oss-120b | 28 | 0.71 | 28.6% | 1785 | 0.00141 | 0 |
| derived_value | openrouter:openai/gpt-oss-20b | 28 | 0.86 | 28.6% | 2083 | 0.00014 | 0 |
| derived_value | openrouter:openai/gpt-oss-safeguard-20b | 28 | 0.57 | 28.6% | 1051 | 0.00073 | 1 |
| derived_value | kev | 28 | 0.14 | 0.0% | 653 | 0.00001 | 0 |
| derived_value | gcp/gemini-3.8-flash | 28 | 0.79 | 28.6% | 5172 | 0.01192 | 0 |
| eligibility_filter | code | 17 | 0.88 | 0.0% | 0 | 0.00000 | 0 |
| eligibility_filter | aws/gpt-oss-120b | 67 | 0.94 | 5.9% | 1921 | 0.00118 | 0 |
| eligibility_filter | openrouter:openai/gpt-oss-20b | 67 | 0.91 | 8.8% | 1413 | 0.00015 | 0 |
| eligibility_filter | openrouter:openai/gpt-oss-safeguard-20b | 67 | 0.76 | 0.0% | 854 | 0.00054 | 4 |
| eligibility_filter | kev | 67 | 0.42 | 0.0% | 536 | 0.00001 | 0 |
| eligibility_filter | gcp/gemini-3.8-flash | 67 | 0.94 | 2.9% | 4015 | 0.00896 | 0 |
| exception_override | aws/gpt-oss-120b | 16 | 1.00 | 0.0% | 1762 | 0.00126 | 0 |
| exception_override | openrouter:openai/gpt-oss-20b | 16 | 0.88 | 12.5% | 2065 | 0.00032 | 0 |
| exception_override | openrouter:openai/gpt-oss-safeguard-20b | 16 | 0.75 | 12.5% | 948 | 0.00063 | 1 |
| exception_override | kev | 16 | 0.00 | 0.0% | 556 | 0.00001 | 0 |
| exception_override | gcp/gemini-3.8-flash | 16 | 1.00 | 0.0% | 4210 | 0.00864 | 0 |
| format | code | 4 | 1.00 | 0.0% | 0 | 0.00000 | 0 |
| format | aws/gpt-oss-120b | 12 | 1.00 | 0.0% | 1397 | 0.00090 | 0 |
| format | openrouter:openai/gpt-oss-20b | 12 | 1.00 | 0.0% | 2465 | 0.00016 | 0 |
| format | openrouter:openai/gpt-oss-safeguard-20b | 12 | 0.83 | 0.0% | 798 | 0.00063 | 1 |
| format | kev | 12 | 0.33 | 0.0% | 702 | 0.00001 | 0 |
| format | gcp/gemini-3.8-flash | 12 | 0.83 | 0.0% | 5933 | 0.01279 | 0 |
| lookup_matrix | code | 72 | 1.00 | 0.0% | 0 | 0.00000 | 0 |
| lookup_matrix | aws/gpt-oss-120b | 92 | 0.72 | 2.2% | 2263 | 0.00122 | 0 |
| lookup_matrix | openrouter:openai/gpt-oss-20b | 92 | 0.63 | 4.3% | 1450 | 0.00018 | 0 |
| lookup_matrix | openrouter:openai/gpt-oss-safeguard-20b | 92 | 0.46 | 2.2% | 1004 | 0.00074 | 11 |
| lookup_matrix | kev | 92 | 0.00 | 2.2% | 698 | 0.00001 | 0 |
| lookup_matrix | gcp/gemini-3.8-flash | 92 | 0.96 | 0.0% | 4993 | 0.01111 | 0 |
| notification_duty | aws/gpt-oss-120b | 4 | 1.00 | 100.0% | 2498 | 0.00181 | 0 |
| notification_duty | openrouter:openai/gpt-oss-20b | 4 | 1.00 | 0.0% | 1525 | 0.00014 | 0 |
| notification_duty | openrouter:openai/gpt-oss-safeguard-20b | 4 | 0.50 | 0.0% | 957 | 0.00053 | 1 |
| notification_duty | kev | 4 | 0.00 | 0.0% | 506 | 0.00001 | 0 |
| notification_duty | gcp/gemini-3.8-flash | 4 | 1.00 | 0.0% | 4579 | 0.01956 | 0 |
| procedure | aws/gpt-oss-120b | 8 | 0.75 | 0.0% | 2342 | 0.00084 | 0 |
| procedure | openrouter:openai/gpt-oss-20b | 8 | 0.50 | 0.0% | 1312 | 0.00008 | 0 |
| procedure | openrouter:openai/gpt-oss-safeguard-20b | 8 | 0.75 | 0.0% | 1022 | 0.00051 | 0 |
| procedure | kev | 8 | 0.00 | 0.0% | 869 | 0.00001 | 0 |
| procedure | gcp/gemini-3.8-flash | 8 | 0.75 | 0.0% | 4477 | 0.00949 | 0 |
| prohibition | code | 12 | 1.00 | 0.0% | 0 | 0.00000 | 0 |
| prohibition | aws/gpt-oss-120b | 68 | 0.85 | 11.8% | 1563 | 0.00114 | 0 |
| prohibition | openrouter:openai/gpt-oss-20b | 68 | 0.91 | 8.8% | 3098 | 0.00018 | 0 |
| prohibition | openrouter:openai/gpt-oss-safeguard-20b | 68 | 0.82 | 5.9% | 800 | 0.00060 | 4 |
| prohibition | kev | 68 | 0.00 | 0.0% | 680 | 0.00001 | 0 |
| prohibition | gcp/gemini-3.8-flash | 68 | 0.82 | 5.9% | 4560 | 0.01083 | 0 |
| required_field | code | 10 | 1.00 | 0.0% | 0 | 0.00000 | 0 |
| required_field | aws/gpt-oss-120b | 34 | 0.81 | 0.0% | 1255 | 0.00091 | 0 |
| required_field | openrouter:openai/gpt-oss-20b | 34 | 0.69 | 0.0% | 1175 | 0.00012 | 0 |
| required_field | openrouter:openai/gpt-oss-safeguard-20b | 34 | 0.62 | 0.0% | 1001 | 0.00075 | 2 |
| required_field | kev | 34 | 0.19 | 0.0% | 645 | 0.00001 | 0 |
| required_field | gcp/gemini-3.8-flash | 34 | 0.81 | 0.0% | 3621 | 0.01022 | 0 |
| role_permission | aws/gpt-oss-120b | 32 | 0.94 | 12.5% | 2063 | 0.00113 | 0 |
| role_permission | openrouter:openai/gpt-oss-20b | 32 | 0.88 | 18.8% | 1752 | 0.00021 | 0 |
| role_permission | openrouter:openai/gpt-oss-safeguard-20b | 32 | 0.75 | 12.5% | 815 | 0.00072 | 0 |
| role_permission | kev | 32 | 0.06 | 0.0% | 632 | 0.00001 | 0 |
| role_permission | gcp/gemini-3.8-flash | 32 | 1.00 | 6.2% | 6256 | 0.01617 | 0 |
| source_of_truth | aws/gpt-oss-120b | 36 | 0.94 | 0.0% | 1697 | 0.00113 | 0 |
| source_of_truth | openrouter:openai/gpt-oss-20b | 36 | 0.94 | 0.0% | 2560 | 0.00018 | 0 |
| source_of_truth | openrouter:openai/gpt-oss-safeguard-20b | 36 | 1.00 | 5.6% | 849 | 0.00068 | 3 |
| source_of_truth | kev | 36 | 0.22 | 0.0% | 679 | 0.00001 | 0 |
| source_of_truth | gcp/gemini-3.8-flash | 36 | 0.89 | 0.0% | 4288 | 0.00842 | 0 |
| state_transition | code | 20 | 0.80 | 0.0% | 0 | 0.00000 | 0 |
| state_transition | aws/gpt-oss-120b | 28 | 0.86 | 0.0% | 1381 | 0.00112 | 0 |
| state_transition | openrouter:openai/gpt-oss-20b | 28 | 0.36 | 0.0% | 1133 | 0.00018 | 0 |
| state_transition | openrouter:openai/gpt-oss-safeguard-20b | 28 | 0.50 | 0.0% | 902 | 0.00051 | 6 |
| state_transition | kev | 28 | 0.14 | 0.0% | 701 | 0.00001 | 0 |
| state_transition | gcp/gemini-3.8-flash | 28 | 0.93 | 0.0% | 4910 | 0.01032 | 0 |
| threshold | code | 3 | 1.00 | 0.0% | 0 | 0.00000 | 0 |
| threshold | aws/gpt-oss-120b | 36 | 0.89 | 16.7% | 1692 | 0.00128 | 0 |
| threshold | openrouter:openai/gpt-oss-20b | 36 | 0.78 | 16.7% | 1403 | 0.00014 | 0 |
| threshold | openrouter:openai/gpt-oss-safeguard-20b | 36 | 0.61 | 5.6% | 1060 | 0.00067 | 4 |
| threshold | kev | 36 | 0.28 | 0.0% | 656 | 0.00001 | 0 |
| threshold | gcp/gemini-3.8-flash | 36 | 0.89 | 11.1% | 5096 | 0.01346 | 0 |

## Choice per type

| Type | Checker | Model | May deny | Measured | Why |
|---|---|---|---|---|---|
| allowed_values | verifier | aws/gpt-oss-120b | True | True | recall 1.00, false deny 0.00%, best was aws/gpt-oss-120b |
| approval | verifier | aws/gpt-oss-120b | True | False | 4 cases (< 10) |
| deadline | verifier | aws/gpt-oss-120b | True | False | 8 cases (< 10) |
| definition | verifier | aws/gpt-oss-120b | True | False | 8 cases (< 10) |
| derived_value | verifier | aws/gpt-oss-120b | False | True | no model with false deny <= 2% and recall >= 50%: remind only |
| eligibility_filter | verifier | openrouter:openai/gpt-oss-safeguard-20b | True | True | recall 0.76, false deny 0.00%, best was openrouter:openai/gpt-oss-safeguard-20b |
| exception_override | verifier | aws/gpt-oss-120b | True | True | recall 1.00, false deny 0.00%, best was aws/gpt-oss-120b |
| format | verifier | openrouter:openai/gpt-oss-20b | True | True | recall 1.00, false deny 0.00%, best was aws/gpt-oss-120b |
| lookup_matrix | verifier | aws/gpt-oss-120b | False | True | no model with false deny <= 2% and recall >= 50%: remind only |
| notification_duty | verifier | aws/gpt-oss-120b | True | False | 4 cases (< 10) |
| procedure | verifier | aws/gpt-oss-120b | True | False | 8 cases (< 10) |
| prohibition | verifier | aws/gpt-oss-120b | False | True | no model with false deny <= 2% and recall >= 50%: remind only |
| required_field | verifier | aws/gpt-oss-120b | True | True | recall 0.81, false deny 0.00%, best was aws/gpt-oss-120b |
| role_permission | verifier | aws/gpt-oss-120b | False | True | no model with false deny <= 2% and recall >= 50%: remind only |
| source_of_truth | verifier | openrouter:openai/gpt-oss-20b | True | True | recall 0.94, false deny 0.00%, best was aws/gpt-oss-120b |
| state_transition | verifier | aws/gpt-oss-120b | True | True | recall 0.86, false deny 0.00%, best was aws/gpt-oss-120b |
| threshold | verifier | aws/gpt-oss-120b | False | True | no model with false deny <= 2% and recall >= 50%: remind only |
