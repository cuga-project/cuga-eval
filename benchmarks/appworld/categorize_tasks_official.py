#!/usr/bin/env python3
"""
Categorize AppWorld tasks using official dataset splits and metadata.
"""

import json
from pathlib import Path


def load_official_split(split_name):
    """Load task IDs from official split file."""
    split_file = Path(f"appworld/data/datasets/{split_name}.txt")
    with open(split_file, "r") as f:
        return [line.strip() for line in f if line.strip()]


def get_task_difficulty(task_id):
    """Get difficulty from task metadata."""
    task_dir = Path(f"appworld/data/tasks/{task_id}")
    metadata_file = task_dir / "ground_truth" / "metadata.json"

    if not metadata_file.exists():
        return None

    with open(metadata_file, "r") as f:
        metadata = json.load(f)
        return metadata.get("difficulty")


def categorize_tasks():
    """Categorize all tasks by test set and difficulty."""

    # Load official splits
    test_normal_ids = load_official_split("test_normal")
    test_challenge_ids = load_official_split("test_challenge")

    # Difficulty mapping
    difficulty_map = {1: "easy", 2: "medium", 3: "hard"}

    # Categorize tasks
    categorization = {
        "normal": {"easy": [], "medium": [], "hard": []},
        "challenge": {"easy": [], "medium": [], "hard": []},
    }

    # Process normal test set
    for task_id in test_normal_ids:
        difficulty = get_task_difficulty(task_id)
        if difficulty in difficulty_map:
            categorization["normal"][difficulty_map[difficulty]].append(task_id)

    # Process challenge test set
    for task_id in test_challenge_ids:
        difficulty = get_task_difficulty(task_id)
        if difficulty in difficulty_map:
            categorization["challenge"][difficulty_map[difficulty]].append(task_id)

    # Print results
    print("=" * 80)
    print("APPWORLD TASKS - OFFICIAL CATEGORIZATION")
    print("=" * 80)
    print()

    for test_set in ["normal", "challenge"]:
        print(f"\n{'=' * 80}")
        print(f"{test_set.upper()} TEST SET")
        print(f"{'=' * 80}")

        for difficulty in ["easy", "medium", "hard"]:
            tasks = sorted(categorization[test_set][difficulty])
            count = len(tasks)

            diff_num = list(difficulty_map.keys())[list(difficulty_map.values()).index(difficulty)]
            print(f"\n{difficulty.upper()} (Difficulty {diff_num}): {count} tasks")
            print("-" * 80)

            # Print tasks in columns
            if tasks:
                for i in range(0, len(tasks), 5):
                    print("  " + "  ".join(tasks[i : i + 5]))

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    for test_set in ["normal", "challenge"]:
        total = sum(len(categorization[test_set][d]) for d in ["easy", "medium", "hard"])
        print(f"\n{test_set.upper()} Test Set: {total} tasks")
        for difficulty in ["easy", "medium", "hard"]:
            count = len(categorization[test_set][difficulty])
            print(f"  - {difficulty.capitalize()}: {count}")

    # Save to JSON
    output_file = "task_categorization.json"
    with open(output_file, "w") as f:
        json.dump(categorization, f, indent=2)

    print(f"\n\nTask categorization saved to: {output_file}")

    return categorization


if __name__ == "__main__":
    categorize_tasks()

# Made with Bob
