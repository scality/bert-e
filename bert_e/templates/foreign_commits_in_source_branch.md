{% extends "message.md" %}

{% block title -%}
Foreign commits detected in source branch
{% endblock %}

{% block message %}
The source branch `{{ src_branch }}` shares history with
`{{ foreign_branch }}`, which is not an ancestor of the target
branch `{{ dst_branch }}`.

This typically happens when the feature branch was accidentally based on
commits from a higher release line rather than directly on `{{ dst_branch }}`.
Common causes include:

- Rebasing on a Bert-E integration branch (e.g. a `w/` branch) instead of
  directly on `{{ dst_branch }}`
- Merging a higher development branch into the feature branch

If your branch was intentionally merged into `{{ foreign_branch }}` before
being backported here, please ensure it is rebased directly on
`{{ dst_branch }}` with no extraneous commits from the higher release line.

{% endblock %}
