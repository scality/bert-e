#{% block title %}{% endblock %}#

{% block message %}
{% endblock %}

{% block footer %}
`Message code: {{ code }}`

{% if active_options %}
*The following options are set:* **{{ active_options|join(', ') }}**
{% else %}
*There are currently no options set. Type* `@scality_wall-e help`
*to obtain the list.*
{% endif %}
{% endblock %}
