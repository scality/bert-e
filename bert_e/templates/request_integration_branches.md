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

Alternatively, there's another way to accomplish this. Simply tag this PR with `/approve` or
`/create_pull_requests`, and it will automatically create the integration branches

{% endblock %}
