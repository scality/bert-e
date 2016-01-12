`Message code: {{ code }}`

{% if active_options %}
The following options are currently active: **{{ active_options|join(', ') }}**
{% else %}
There are currently no active options. Type `@scality_wall-e help`
to obtain the list.
{% endif %}
