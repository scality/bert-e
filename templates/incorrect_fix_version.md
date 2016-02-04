{% extends "message.md" %}

{% block title -%}
Incorrect fix version
{% endblock %}

{% block message %}
The `Fix Version/s` in issue {{ issue.key }}{% if subtask %},
parent of sub-task {{ subtask.key }},{% endif %} contains:

{% for version in issue_versions %}
* `{{ version }}`
{% else %}
* *None*
{% endfor %}

Considering where you are trying to merge, I expected to find:

{% for version in expect_versions %}
* `{{ version }}`
{% else %}
* *None*
{% endfor %}

Please check the `Fix Version/s` of {{ issue }}, or the target
branch of this pull request.
{% endblock %}
