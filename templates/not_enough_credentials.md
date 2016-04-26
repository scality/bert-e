{% extends "message.md" %}

{% block title -%}
Insufficient credentials
{% endblock %}

{% block message %}
I'm sorry **{{ author }}**. I'm afraid I can't do that.

{% if self_pr %}
You cannot use the privileged `{{ command }}` command in your own pull
request.
{% else %}
You don't have enough credentials to use the `{{ command }}` command.
{% endif %}

Please **edit** or **delete** the corresponding comment(s) so I can move on.
{% endblock %}
