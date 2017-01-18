#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  wb_jq.py
#
#  Copyright 2017 Jelle Smet <development@smetj.net>
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
#

from wishbone import Actor
from wishbone.utils import StructuredDataFile
import pyjq
from wishbone.error import InvalidData
from gevent.lock import Semaphore

SCHEMA = {
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


class JQExpressions(object):

    '''An object which holds the JQ expressions to match against docs.
    '''

    def __init__(self):

        self._lock = Semaphore()
        self._content = {}

    def add(self, name, expression, queue, payload):
        '''Adds the provided expression.

        :param str name: The name of the expression.
        :param str expression: The jq expression.
        :param str queue: The name of the queue submit matching events to.
        :param dict payload: The payload to include to matching events.
        '''

        with self._lock:
            self._content[name] = {"queue": queue, "expression": self.__compileExpression(expression), "payload": payload}

    def delete(self, name):
        '''Deletes the expression.

        param str name: The name of the expression.
        '''
        with self._lock:
            try:
                del(self._content[name])
            except KeyError:
                pass

    def get(self, name):
        '''Returns the expression.

        :param str name: The name of the expression.
        :return: expression, queue, payload
        '''

        with self._lock:
            return self._content[name]["expression"], self._content[name]["queue"], self._content[name]["payload"]

    def getAll(self):
        '''Returns the expression.

        :param str name: The name of the expression.
        :return: generator returning expression, queue, payload
        '''

        with self._lock:
            for name, value in self._content.iteritems():
                yield name, value["expression"], value["queue"], value["payload"]

    def size(self):
        '''Returns the number of stored expressions.self

        :return: The number of stored expressions
        '''

        with self._lock:
            return len(self._content)

    def __compileExpression(self, expression):
        '''Compiles the provided `expression`.

        :param str expression: The jq expression to compile
        :return: The compiled jq expression.
        '''

        try:
            return pyjq.compile(expression)
        except Exception as err:
            message = err.message.replace("\n", " -> ")
            raise Exception(message)


class JQ(Actor):

    '''**JSON pattern matching using jq expressions.**

    Evalutes (JSON) data structures against a set of jq expressions to decide
    which queue to forward the event to.

    JQ expressions
    --------------

    More information about jq expressions can be found here:

        - https://stedolan.github.io/jq/manual/


    Jq expressions need to return either **True** or **False**, otherwise this
    module will consider the result to be invalid and therefor skip the
    condition.

    Conditions
    ----------

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

    Reading conditions from disk
    ----------------------------

    Events submitted to the <inotify_events> directory are supposed to contain
    file or directory names.  When a path is a directory, the module will try
    to load all files within the said directory.  This is NOT done
    recursively.  When a path is a file, the file will be treated as a single
    condition or a list of conditions.

    Both JSON and YAML are supported.  Typically one feeds this queue with the
    events generated by the wishbone.input.inotify module.

    Parameters:

        - selection(str)("@data")
           |  The root part of the event to evaluate.
           |  Use an empty string to refer to the complete event.

        - conditions(dict)([])
           |  A dictionary consisting out of expression, queue, payload.

    Queues:

        - inbox
           |  Incoming events.

        - outbox
           |  Events matching a rule

        - no_match
           |  Events which did not match at least one rule.

        - inotify_events
           |  Reads the condition from the referred paths of incoming events.

        -
    '''

    def __init__(self, actor_config, selection="@data", conditions=[]):
        Actor.__init__(self, actor_config)

        self.pool.createQueue("inbox")
        self.pool.createQueue("outbox")
        self.pool.createQueue("no_match")
        self.pool.createQueue("inotify_events")
        self.registerConsumer(self.consume, "inbox")
        self.registerConsumer(self.processInotifyEvent, "inotify_events")
        self.disk_conditions = StructuredDataFile(schema=SCHEMA, expect_json=False)
        self.jq_expressions = JQExpressions()

    def preHook(self):

        for condition in self.kwargs.conditions:
            try:
                self.jq_expressions.add(condition["name"], condition["expression"], condition["queue"], condition.get("payload", {}))
            except Exception as err:
                self.logging.error("Failed to add condition %s. Skipped. Reason: %s." % (condition["name"], err))

    def processInotifyEvent(self, event):

        '''Processes the "load condition event".

        @data is supposed to contain: { "path": "/", "inotify_type": "SOME_TYPE" }
        '''

        d = event.get()
        if d["inotify_type"] in ["IN_DELETE", "IN_MOVED_FROM"]:
            content = self.disk_conditions.get(d["path"])
            self.disk_conditions.delete(d["path"])
            self.jq_expressions.delete(content["name"])
            self.logging.info("Successfully deleted condition '%s'. In total '%s' conditions active." % (d["path"], self.jq_expressions.size()))

        elif d["inotify_type"] in ["IN_CLOSE_WRITE", "IN_MOVED_TO", "WISHBONE_INIT"]:
            condition = self.disk_conditions.load(d["path"])
            self.jq_expressions.add(condition["name"], condition["expression"], condition["queue"], condition.get("payload", {}))

            self.logging.info("Successfully loaded condition '%s'. In total '%s' conditions active." % (d["path"], self.jq_expressions.size()))
        else:
            self.logging.debug("Received inotify event of type '%s' for file '%s' but it's ignored by design." % (d["inotify_type"], d["path"]))

    def consume(self, event):

        matched = False
        data = event.get(self.kwargs.selection)

        for name, expression, queue, payload in self.jq_expressions.getAll():
            if self.pool.hasQueue(queue):
                if self.evaluate_expression(name, expression, data):
                    matched = True
                    e = event.clone()
                    e.set(name, "@tmp.%s.rule" % (self.name))
                    if payload != {}:
                        for key, value in payload.iteritems():
                            e.set(value, key)
                    self.submit(e, self.pool.getQueue(queue))
            else:
                self.logging.warning("Condition '%s' has queue '%s' defined but nothing connected." % (name, queue))

        if not matched:
            # self.logging.debug("Condition '%s' DOES NOT match '%s'." % (name, data))
            self.submit(event, self.pool.queue.no_match)

    def evaluate_expression(self, name, jq_expression, value):
        '''Evaluates `jq_expression` against `value`.

        param str name: The name of the expression
        param _pyjq.Script jq_expression: A compiled pyjq expression
        param dict value: The dict(json) to evaluate
        '''

        result = jq_expression.first(value)

        if isinstance(result, bool) or result is None:
            if result:
                self.logging.debug("Condition '%s' matches '%s'." % (name, value))
                self.logging.debug("Condition '%s' matches." % (name))
                return True
            else:
                self.logging.debug("Condition '%s' DOES NOT match '%s'." % (name, value))
                return False
        else:
            self.logging.error("Jq expression '%s' does not return a bool therefor it is skipped." % (name))
            return False
