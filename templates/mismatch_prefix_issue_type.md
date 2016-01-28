{% extends "message.md" %}

{% block title -%}
Issue and branch mismatch
{% endblock %}

{% block message %}
Branch prefix `{{ prefix }}` mismatches
jira issue type `{{ expected }}`.

Please correct and comment this pull request to try again.
{% endblock %}
