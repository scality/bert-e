{% extends "message.md" %}

{% block title -%}
Incorrect source branch name
{% endblock %}

{% block message %}
I cannot merge the branch `{{ source.name }}` into
`{{ destination.name }}`.

Make sure the source branch contains one of these prefixes:

{% for prefix in valid_prefixes %}
* `{{ prefix }}/`
{% endfor %}

Please rename the source branch and create a new pull request.
{% endblock %}
