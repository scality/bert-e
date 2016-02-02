{% extends "message.md" %}

{% block title -%}
Missing Jira issue
{% endblock %}

{% block message %}
It is mandatory to specify a Jira issue in the source branch name
in order to merge into `{{ dest_branch }}`. The issue key must follow
the prefix of the branch.

I could not find such an issue in `{{ source_branch }}`.
{% endblock %}
