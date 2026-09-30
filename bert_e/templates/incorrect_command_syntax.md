{% extends "message.md" %}

{% block title -%}
Incorrect command syntax
{% endblock %}

{% block message %}
It seems that your command syntax is incorrect. The correct usage is:

```
@{{ robot }} option[=argument]
```
{% if keyword is defined and keyword %}
Options take their argument after an equal sign, without spaces, e.g.
`/{{ keyword }}=<value>` or `@{{ robot }} {{ keyword }}=<value>`.
{% endif %}
Please **edit** or **delete** the corresponding comment so I can move on.

{% endblock %}
