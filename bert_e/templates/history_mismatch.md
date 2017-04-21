{% extends "message.md" %}

{% block title -%}
History mismatch
{% endblock %}

{% block message %}
Merge commit #{{ commit }} on the integration branch
`{{ integration_branch.name }}` is merging a branch which is neither the current
branch `{{ feature_branch.name }}` nor the development branch
`{{ development_branch.name }}`.

It is likely due to a rebase of the branch `{{ feature_branch.name }}` and the
merge is not possible until all related `w/*` branches are deleted or updated.

**Please use the `reset` command to have me reinitialize these branches.**

{% endblock %}
