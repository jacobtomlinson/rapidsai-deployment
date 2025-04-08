#!/usr/bin/env python
# Run this script to generate the release issue checklist for easy pasting into GitHub

from pathlib import Path

import frontmatter

# Get the full path to the directory where this script lives
script_name = Path(__file__).resolve()
script_dir = script_name.parent

print(
    """# Release checklist

For the upcoming release we need to verify our documentation. This is a best efforts activity
so please refer to the checklist from the previous release and focus on pages that were not
verified last time.

## Verify pages

- Look at the nightly build of each page listed below
- Check page renders correctly
- Check for spelling/grammar problems
- Check that the instructions work as expected
- Ensure legacy pages with out of date instructions have a content warning
- If page needs updating convert the task to an issue and open a PR that closes the issue

"""
)

priority_lists = {
    "index": {"name": "Index/Non-technical", "pages": []},
    "p0": {"name": "P0", "pages": []},
    "p1": {"name": "P1", "pages": []},
    "p2": {"name": "P2", "pages": []},
}

# Walk all files recursively in the source directory
for file in (script_dir.parent / "source").rglob("*"):
    if file.is_file() and file.suffix in [".ipynb", ".md"]:
        if "_includes" in file.parts:
            continue
        if ".ipynb_checkpoints" in file.parts:
            continue
        if "index.md" in file.parts:
            rel_path = file.parent
        else:
            rel_path = file
        rel_path = rel_path.relative_to(script_dir.parent / "source")
        priority = "p2"
        if file.suffix == ".md":
            try:
                priority = str(frontmatter.load(file).metadata["review_priority"])
            except KeyError:
                pass
        elif file.suffix == ".ipynb":
            # TODO - add support for ipynb review_priority
            pass

        if rel_path.name:
            rel_path = str(rel_path.with_suffix(""))
        elif str(rel_path) == ".":
            rel_path = ""
        else:
            rel_path = str(rel_path)

        file_info = {
            "file": file,
            "url": "https://docs.rapids.ai/deployment/nightly/" + rel_path,
            "priority": priority,
        }
        if priority in priority_lists:
            priority_lists[priority]["pages"].append(file_info)
        else:
            raise ValueError(f"Unknown review_priority '{priority}' for page {file}")

for data in priority_lists.values():
    pages = data["pages"]
    if not pages:
        continue
    print(f"### {data['name']}\n")
    for page in sorted(pages, key=lambda x: x["url"]):
        print(f"- [ ] {page['url']}")
    print()

print(f"_Issue text generated by {script_name.parent.name}/{script_name.name}._")
