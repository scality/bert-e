{% extends "message.md" %}

{% block title -%}
Wrong destination branch
{% endblock %}

{% block message %}
This pull request targets branch `{{ dst_branch }}` but this branch doesn't exist.

It is very likely that the development branch was archived before the pull
request got merged.

Please edit the pull request to target a valid development branch.
{% endblock %}
