{% extends "message.md" %}

{% block title -%}
Incorrect pull request number
{% endblock %}

{% block message %}
The pull request **{{ pr_id }}** does not appear to be a valid pull request
number.

Please specify a valid pull request number in a further comment so I can
move on.
{% endblock %}
