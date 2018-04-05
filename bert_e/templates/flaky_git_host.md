{% extends "message.md" %}

{% block title -%}
Temporary {{ git_host }} failure
{% endblock %}

{% block message %}
I've had trouble contacting the git host. Just post a comment on this pull request to wake me up.
{% endblock %}
