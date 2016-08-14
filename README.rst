::

              __       __    __
    .--.--.--|__.-----|  |--|  |--.-----.-----.-----.
    |  |  |  |  |__ --|     |  _  |  _  |     |  -__|
    |________|__|_____|__|__|_____|_____|__|__|_____|
                                       version 2.2.0

    Build composable event pipeline servers with minimal effort.



    ================
    wishbone.flow.jq
    ================

    Version: 1.0.0

    JSON pattern matching using jq expressions.
    -------------------------------------------


        Evalutes (JSON) data structures against a set of jq expressions to decide
        which queue to forward the event to.

        JQ expressions
        --------------

        More information about jq expressions can be found here:

            - https://stedolan.github.io/jq/manual/


        Jq expressions need to return either **True** or **False**, otherwise this
        module will consider the result to be invalid and therefor skip the
        condition.

        Module level conditions
        -----------------------

        The module accepts the <conditions> parameter which is a list of
        conditions to evaluate against each data structure coming in.
        Each condition should have following format:

        JSON-schema::

            {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string"
                },
                "expression": {
                    "type": "string"
                },
                "queue": {
                    "type": "string"
                },
                "payload": {
                    "type": "object",
                    "patternProperties": {
                        ".*": {
                            "type": [
                                "string",
                                "number"
                            ],
                        }
                    }
                },
            },
            "required": ["name", "expression", "queue"],
            "additionalProperties": False
            }


        Example::

            { "name": "test",
              "expression": ".greeting | test( "hello" )",
              "queue": "outbox",
              "payload": {
                "@tmp.some.key": 1,
              }
            }

        Disk level conditions
        ---------------------

        The directory <location> contains the conditions in YAML format. One
        condition is one file.  Files not having '.yaml' extension are ignored.

        This directory is monitored for changes and automatically reloaded
        whenever something changes.

        The rules should have following format:

        JSON-schema::

            {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string"
                },
                "queue": {
                    "type": "string"
                },
                "payload": {
                    "type": "object",
                    "patternProperties": {
                        ".*": {
                            "type": [
                                "string",
                                "number"
                            ],
                        }
                    }
                },
            },
            "required": ["expression", "queue"],
            "additionalProperties": False
            }

        Example::

            queue: nagios
            expression: '.type | test( "nagios" )'

        payload
        -------

        The payload is a dictionary where keys are wishbone event references.


        Parameters:

            - selection(str)("@data")
               |  The root part of the event to evaluate.
               |  Use an empty string to refer to the complete event.

            - conditions(dict)([])
               |  A dictionary consisting out of expression, queue, payload.

            - location(str)("")
               |  A directory containing rules.  This directory will be monitored
               |  for changes and automatically read for changes.
               |  An empty value disables this functionality.


        Queues:

            - inbox
               |  Incoming events.

            - no_match
               |  Events which did not match at least one rule.

