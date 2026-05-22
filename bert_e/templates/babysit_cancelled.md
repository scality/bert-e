{% extends "message.md" %}

{% block title -%}
Babysit: Cancelled
{% endblock %}

{% block message %}
**Babysit mode has been cancelled** because new commits were pushed to the branch.

Previous retries were for commit `{{ previous_commit[:7] }}`, but the current commit is `{{ current_commit[:7] }}`.

If you want to enable automatic retries for the new commits, please comment `@{{ robot }} babysit` again.
{% endblock %}

