{% extends "message.md" %}

{% block title -%}
Request integration branches
{% endblock %}

{% block message %}
Waiting for integration branch creation to be requested by the user.

To request integration branches, please comment on this pull request with the following command:

```
/create_integration_branches
```
{% endblock %}
