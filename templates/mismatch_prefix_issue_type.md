{% extends "message.md" %}

{% block title -%}
Issue type vs branch prefix mismatch
{% endblock %}

{% block message %}
The specified branch prefix, `{{ prefix }}`, does not correspond
to the issue type `{{ expected }}` specified in {{ issue }}.

The following table shows the accepted pairs:

Jira issue type  |  accepted prefix
-----------------|------------------
{% for pair in pairs -%}
`{{ pair }}` | `{{ pairs[pair] }}`
{% endfor %}

To fix this problem:

- either correct the issue type in Jira, and comment this pull request to try again,
- or, rename the source branch, and open a new pull request.
{% endblock %}
