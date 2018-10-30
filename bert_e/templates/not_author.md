{% extends "message.md" %}

{% block title -%}
Not Author
{% endblock %}

{% block message %}
I'm afraid I cannot do that, @{{ author }}:

Only the author of the pull request @{{ pr_author }} can use this command.

Please **delete** the corresponding comment so I can move on.
{% endblock %}
