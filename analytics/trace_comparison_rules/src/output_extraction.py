from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple


def extract_plan(text: str) -> List[str]:
    """
    Extracts the plan as a list of steps.
    Detects JSON-like lists or numbered lists.
    """
    # Case 1: JSON array present (Example 2 and 3)
    json_list_match = re.search(r"\[\s*\".*?\]\s*", text, re.DOTALL)
    if json_list_match:
        try:
            lst = json.loads(json_list_match.group())
            if isinstance(lst, list):
                return lst
        except json.JSONDecodeError:
            pass

    # Case 2: Numbered list plan (Example 1)
    steps = re.findall(r"\n\s*\d+\.\s+(.*)", text)
    if steps:
        return steps

    # Case 3: Fallback – look for lines containing important words
    fallback = [
        line.strip()
        for line in text.split("\n")
        if any(w in line.lower() for w in ["call", "api", "store", "extract", "loop", "prepare"])
    ]
    return fallback


def extract_dict_block(text, key="variable_name"):
    start = text.find("{")
    if start == -1:
        return None

    # find first block that contains the key
    for pos in range(len(text)):
        if text[pos] == "{":
            level = 1
            i = pos + 1
            while i < len(text) and level > 0:
                if text[i] == "{":
                    level += 1
                elif text[i] == "}":
                    level -= 1
                i += 1

            block = text[pos:i]
            if key in block:
                return block

    return None


def extract_final_output_block(text: str) -> Dict[str, Any]:
    """
    Searches for a dictionary-like final output block:
    {'variable_name': 'xxx', 'description': '...', 'value': ... }
    """
    result = {"variable_name": None, "description": None, "value": None}

    # Match Python dict-like output
    # out = re.search(r"\{[^{}]*variable_name[^{}]*\}", text, re.DOTALL)
    out = extract_dict_block(text)
    if not out:
        return result

    # block = out.group()

    # Extract individual fields
    var_match = re.search(r"['\"]variable_name['\"]\s*:\s*['\"]([^'\"]+)['\"]", out)
    desc_match = re.search(r"['\"]description['\"]\s*:\s*['\"]([^'\"]+)['\"]", out)
    val_match = re.search(r"['\"]value['\"]\s*:\s*([^,'}]+)", out)

    if var_match:
        result["variable_name"] = var_match.group(1).strip()
    if desc_match:
        result["description"] = desc_match.group(1).strip()
    if val_match:
        result["value"] = val_match.group(1).strip()

    return result


def extract_api_code_planner_schema(text: str) -> Dict[str, Any]:
    """Extracts schema fields from a single example text."""
    plan = extract_plan(text)
    final_output = extract_final_output_block(text)

    return {"plan": plan, "final_output": final_output}


################################################################################
def extract_reflection_fields(text: str) -> Dict[str, str]:
    """
    Extract sections:
      - overall_status
      - progress_summary
      - strategic recommendation

    Ensures that the NEXT header line is NOT included in the previous value.
    """

    decoded = text.replace("\r\n", "\n").replace("\r", "\n")

    # ---------- heading normalization ----------
    def normalize(line: str) -> str:
        s = line.strip()
        s = s.strip("*_`#> -\t")
        s = re.sub(r"\s+", " ", s)
        return s.lower()

    # What we are looking for
    heading_aliases = {
        "overall_status": ("overall status",),
        "progress_summary": ("progress summary",),
        "strategic recommendation": ("strategic recommendation",),
    }

    # ---------- detect header lines ----------
    lines = decoded.split("\n")

    header_positions: List[Tuple[str, int]] = []

    for i, line in enumerate(lines):
        norm = normalize(line)
        for key, needles in heading_aliases.items():
            if any(n in norm for n in needles):
                header_positions.append((key, i))
                break

    # keep only first occurrence per key
    first_pos = {}
    for key, pos in header_positions:
        if key not in first_pos:
            first_pos[key] = pos

    if not first_pos:
        return {}

    ordered = sorted(first_pos.items(), key=lambda kv: kv[1])

    # ---------- slice sections ----------
    result: Dict[str, str] = {}

    for idx, (key, header_line_idx) in enumerate(ordered):
        start = header_line_idx + 1
        end = ordered[idx + 1][1] if idx + 1 < len(ordered) else len(lines)

        value = "\n".join(lines[start:end]).strip()
        result[key] = value

    return result


def extract_reflection_fields_v2(text: str) -> Dict[str, str]:
    """
    Extract overall_status_analysis and strategic_recommendation from
    Reflection agent output (cuga_lite_top rules).

    Handles markdown headers, bold labels, and plain-text section titles.
    """
    decoded = text.replace("\r\n", "\n").replace("\r", "\n")

    def normalize(line: str) -> str:
        s = line.strip().strip("*_`#> -\t")
        return re.sub(r"\s+", " ", s).lower()

    # _ignored keys act as section boundaries for slicing but are not returned.
    heading_aliases = {
        "overall_status_analysis": (
            "overall status analysis",
            "overall status",
            "status analysis",
        ),
        "_progress_summary": (
            "summary of progress",
            "progress summary",
        ),
        "strategic_recommendation": (
            "strategic recommendation",
            "recommendation",
        ),
    }

    lines = decoded.split("\n")
    first_pos: Dict[str, int] = {}
    for i, line in enumerate(lines):
        norm = normalize(line)
        for key, needles in heading_aliases.items():
            if key not in first_pos and any(n in norm for n in needles):
                first_pos[key] = i
                break

    if not first_pos:
        return {}

    ordered = sorted(first_pos.items(), key=lambda kv: kv[1])
    result: Dict[str, str] = {}
    for idx, (key, header_idx) in enumerate(ordered):
        start = header_idx + 1
        end = ordered[idx + 1][1] if idx + 1 < len(ordered) else len(lines)
        if not key.startswith("_"):
            result[key] = "\n".join(lines[start:end]).strip()

    return result


def extract_code_agent_content(text: str) -> Dict[str, str]:
    """
    Extracts the textual content from Code Agent output, stripping any
    fenced Python code blocks (```python ... ```).

    Returns the remaining text which may be brief reasoning before the code,
    a plain-language answer, or empty string if the output is code-only.
    """
    content = re.sub(r"```(?:python)?\s*.*?```", "", text, flags=re.DOTALL)
    return {"content": content.strip()}


###############################################################
# TESTING
if __name__ == "__main__":
    example1 = """Based on the user's goal and the available tools, here's a step-by-step plan:\n\n1. First, call the `amazon_show_cart_cart_get` API to retrieve the list of products in the cart. Store the response in a variable called `cart_products`.\n\n2. Initialize an empty list called `products_to_move` to keep track of products that need to be moved to the wish list.\n\n3. Loop through each product in the `cart_products` list. For each product, do the following:\n\n   a. Extract the `product_id` from the product object.\n\n   b. Call the `amazon_show_product_products_product_id_get` API with the `product_id` to get the product details. Store the response in a variable called `product_details`.\n\n   c. Check the `rating` field in the `product_details` object. If the rating is less than 4.2, add the `product_id` to the `products_to_move` list.\n\n4. After the loop, you now have a list of product IDs that need to be moved to the wish list. Initialize an empty list called `moved_products` to store the details of the products that were successfully moved.\n\n5. Loop through each `product_id` in the `products_to_move` list. For each product, do the following:\n\n   a. Call the `amazon_move_product_from_cart_to_wish_list_cart_to_wish_list_product_id_post` API with the `product_id` to move the product to the wish list. Store the response in a variable called `move_response`.\n\n   b. Check if the `move_response` contains a success message. If it does, add the `product_id` to the `moved_products` list.\n\n6. After the loop, you now have a list of product IDs that were successfully moved to the wish list. Call the `amazon_show_wish_list_wish_list_get` API to retrieve the updated wish list. Store the response in a variable called `wish_list_products`.\n\n7. Filter the `wish_list_products` list to only include products whose `product_id` is in the `moved_products` list. Store the filtered list in a variable called `final_moved_products`.\n\n8. Prepare the final result as a JSON serializable dictionary: `{'variable_name': 'moved_products_list', 'description': 'A list of products that were moved to the wish list.', 'value': final_moved_products}`.\n\n9. Print the final result dictionary as a JSON string using `print(json.dumps(result_dict))`"""
    example2 = """```json\n[\n  "1. To list all products currently in the user\'s Amazon cart, start by calling the `amazon_show_cart_cart_get` API. This API will return the details of the user\'s cart, including a list of cart items.",\n  "2. Extract the `cart_items` array from the API response. Each item in this array contains details such as `product_id` and `product_name`.",\n  "3. Prepare the result as a JSON serializable dictionary. The dictionary will have the structure: `{\'variable_name\': \'cart_items\', \'description\': \'An array of cart item objects, each containing product_id and product_name.\', \'value\': cart_items}`.",\n  "4. Print the final result dictionary as a JSON string using `print(json.dumps(result_dict))`."\n]\n```"""
    example3 = """### Thought Process and Reasoning\n\nTo achieve the user\'s goal of listing all products in the cart along with their ratings, we need to follow a two-step process:\n\n1. **Retrieve the list of products in the cart**: We will use the `amazon_show_cart_cart_get` API to get the list of products currently in the user\'s cart. This API returns a list of cart items, including product IDs and names.\n\n2. **Fetch the rating for each product**: For each product in the cart, we will use the `amazon_show_product_products_product_id_get` API to retrieve detailed information about the product, specifically its rating.\n\nBy chaining these two API calls, we can compile a list of products in the cart along with their respective ratings.\n\n### Assessment of Tool Schema Sufficiency\n\nThe available tool schemas provide the necessary APIs to achieve the user\'s goal:\n- `amazon_show_cart_cart_get` to list the products in the cart.\n- `amazon_show_product_products_product_id_get` to get the rating for each product.\n\nTherefore, we have sufficient APIs to complete the task without needing to report any missing APIs.\n\n### Plan\n\nHere is the step-by-step plan to achieve the user\'s goal:\n\n```json\n[\n  "1. Call the `amazon_show_cart_cart_get` API to retrieve the list of products currently in the cart. Store the response in a variable named `cart_details`.",\n  "2. Extract the list of `cart_items` from `cart_details`.",\n  "3. Initialize an empty list called `products_with_ratings` to store the product details along with their ratings.",\n  "4. Loop through each `item` in the `cart_items` list.",\n  "5. For each `item`, extract the `product_id`.",\n  "6. Call the `amazon_show_product_products_product_id_get` API using the `product_id` to fetch the product details, including its rating. Store the response in a variable named `product_details`.",\n  "7. Extract the necessary information (product ID, name, and rating) from `product_details` and add it to the `products_with_ratings` list.",\n  "8. After processing all items, prepare the final result as a JSON serializable dictionary: `{\'variable_name\': \'cart_products_with_ratings\', \'description\': \'A list of products in the cart along with their ratings.\', \'value\': products_with_ratings}`.",\n  "9. Print the final result dictionary as a JSON string using `print(json.dumps(result_dict))`."\n]\n```\n\n### Final Output\n\nThe final output will be a JSON string representing a dictionary with the required details:\n```json\n```json\n{\n  "variable_name": "cart_products_with_ratings",\n  "description": "A list of products in the cart along with their ratings.",\n  "value": [\n    {"product_id": 1, "name": "Product Name 1", "rating": 4.5},\n    {"product_id": 2, "name": "Product Name 2", "rating": 3.8},\n    ...\n  ]\n}\n```json\n```"""

    examples = [example1, example2, example3]

    output = [extract_api_code_planner_schema(e) for e in examples]

    print(json.dumps(output, indent=4))
