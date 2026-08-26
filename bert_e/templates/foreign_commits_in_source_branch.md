{% extends "message.md" %}

{% block title -%}
Foreign commits detected in source branch
{% endblock %}

{% block message %}
The source branch `{{ src_branch }}` shares history with the following
release line(s), which are not ancestors of `{{ dst_branch }}`:

{% for branch in foreign_branches %}
- `{{ branch }}`
{% endfor %}

This typically happens when the feature branch was accidentally based on
commits from a higher release line rather than directly on `{{ dst_branch }}`.
Common causes include:

- Rebasing on a Bert-E integration branch (e.g. a `w/` branch) instead of
  directly on `{{ dst_branch }}`
- Branching from a higher development branch instead of `{{ dst_branch }}`
- Merging a higher development branch into the feature branch

**How to fix**

Create a new branch directly from `{{ dst_branch }}` and cherry-pick your
changes onto it:

```
git checkout -b <new-branch-name> origin/{{ dst_branch }}
git cherry-pick <your-commits>
```

Then open a new pull request from that branch.

**If this is a false positive**

If your branch is a legitimate backport and was previously merged into one
of the branches above before being extended with new commits, an
administrator can bypass this check with:

```
@bert-e bypass_source_branch_lineage
```

{% endblock %}
