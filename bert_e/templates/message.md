# {% block title %}{% endblock %}

{% block message %}
{% endblock %}

{% block footer %}
{% if active_options %}
*The following options are set:* **{{ active_options|join(', ') }}**
{% endif %}
{% endblock %}
