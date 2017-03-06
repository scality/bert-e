{% extends "message.md" %}

{% block title -%}
Incorrect command syntax
{% endblock %}

{% block message %}
It seems that your command syntax is incorrect. The correct usage is:

```
@{{ robot_username }} option[=argument]
```

Please **edit** or **delete** the corresponding comment so I can move on.

{% endblock %}
