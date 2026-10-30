"""A small query language for issues, in the spirit of JQL.

    project-scoped:  type = bug AND status != done
                     assignee = currentUser() AND priority IN (high, highest)
                     title ~ "login" OR text ~ checkout
                     epic IS NOT EMPTY AND updated >= 2026-10-01
                     status = done ORDER BY updated DESC, key ASC

Fields: key, type, status, priority, assignee, reporter, label, component, version, epic, sprint,
title, text, created, updated, duedate.
Operators: =  !=  ~ (contains)  !~  IN (…)  NOT IN (…)  IS EMPTY  IS NOT EMPTY  and, for dates, < > <= >=.
Connectors: AND (binds tighter), OR, and parentheses.

`parse(text, user)` returns (Q, ordering). Any mistake raises QueryError with a message for the user.
"""

import datetime
import re

from django.db.models import Q
from django.utils.translation import gettext as _

from .models import IssueType, Priority

TOKEN = re.compile(r'\s*(?:(?P<str>"(?:[^"\\]|\\.)*")|(?P<op><=|>=|!=|!~|<|>|=|~|\(|\)|,)|(?P<word>[^\s()=!<>~,"]+))')
TEXT_FIELDS = {"reporter", "label", "component", "version", "sprint", "assignee"}
DATE_FIELDS = {"created", "updated", "duedate"}
KNOWN = {"key", "type", "status", "priority", "epic", "title", "text"} | TEXT_FIELDS | DATE_FIELDS
ORDERABLE = {"key", "type", "status", "priority", "created", "updated", "duedate", "title"}
FIELD_TO_DB = {
    "type": "issue_type", "status": "status", "priority": "priority", "duedate": "due_date",
    "created": "created_at", "updated": "updated_at", "title": "title", "key": "number",
}


class QueryError(Exception):
    pass


def tokenize(text):
    tokens, pos = [], 0
    text = text.strip()
    while pos < len(text):
        match = TOKEN.match(text, pos)
        if not match or match.end() == pos:
            raise QueryError(_("Unexpected text near “%(text)s”.") % {"text": text[pos:pos + 12]})
        pos = match.end()
        kind = match.lastgroup
        value = match.group(kind)
        if kind == "str":
            tokens.append(("value", value[1:-1].replace('\\"', '"')))
        elif kind == "op":
            tokens.append(("op", value))
        else:
            tokens.append(("word", value))
    return tokens


class Parser:
    def __init__(self, tokens, project, user):
        self.tokens, self.i, self.project, self.user = tokens, 0, project, user

    def peek(self, n=0):
        return self.tokens[self.i + n] if self.i + n < len(self.tokens) else (None, None)

    def take(self):
        token = self.peek()
        self.i += 1
        return token

    def is_word(self, word, n=0):
        kind, value = self.peek(n)
        return kind == "word" and value.upper() == word

    def expect_op(self, op):
        kind, value = self.take()
        if value != op:
            raise QueryError(_("Expected “%(op)s”.") % {"op": op})

    def or_expr(self):
        q = self.and_expr()
        while self.is_word("OR"):
            self.take()
            q = q | self.and_expr()
        return q

    def and_expr(self):
        q = self.factor()
        while self.is_word("AND"):
            self.take()
            q = q & self.factor()
        return q

    def factor(self):
        kind, value = self.peek()
        if value == "(":
            self.take()
            q = self.or_expr()
            self.expect_op(")")
            return q
        return self.clause()

    def value(self):
        kind, value = self.take()
        if kind is None:
            raise QueryError(_("A value is missing."))
        if kind == "word" and self.peek() == ("op", "("):
            # a function call: name, then empty parentheses
            self.take()
            self.expect_op(")")
            if value.lower() == "currentuser":
                return self.user
            raise QueryError(_("Unknown function %(name)s().") % {"name": value})
        return value

    def clause(self):
        kind, field = self.take()
        if kind != "word":
            raise QueryError(_("Expected a field name."))
        field = field.lower()
        if field == "version":
            field = "version"
        if field not in KNOWN:
            raise QueryError(_("Unknown field “%(field)s”.") % {"field": field})
        if self.is_word("IS"):
            self.take()
            negate = False
            if self.is_word("NOT"):
                self.take()
                negate = True
            if not self.is_word("EMPTY"):
                raise QueryError(_("Expected EMPTY after IS."))
            self.take()
            q = self.empty_q(field)
            return ~q if negate else q
        if self.is_word("NOT") and self.is_word("IN", 1):
            self.take()
            self.take()
            return ~self.in_q(field, self.values())
        if self.is_word("IN"):
            self.take()
            return self.in_q(field, self.values())
        kind, op = self.take()
        if kind != "op":
            raise QueryError(_("Expected an operator after “%(field)s”.") % {"field": field})
        return self.compare(field, op, self.value())

    def values(self):
        self.expect_op("(")
        items = [self.value()]
        while self.peek()[1] == ",":
            self.take()
            items.append(self.value())
        self.expect_op(")")
        return items

    def empty_q(self, field):
        if field in TEXT_FIELDS:
            name = {"reporter": "reporter", "assignee": "assignee", "epic": "epic", "sprint": "sprint"}.get(field)
            if field in ("label", "component", "version"):
                many = {"label": "labels", "component": "components", "version": "fix_versions"}[field]
                return Q(**{f"{many}__isnull": True})
            return Q(**{f"{name}__isnull": True})
        if field == "epic":
            return Q(epic__isnull=True)
        if field in DATE_FIELDS:
            return Q(**{f"{FIELD_TO_DB[field]}__isnull": True})
        raise QueryError(_("EMPTY does not apply to “%(field)s”.") % {"field": field})

    def in_q(self, field, items):
        q = Q()
        for item in items:
            q = q | self.compare(field, "=", item)
        return q

    def compare(self, field, op, value):
        if field == "key":
            number = value.rsplit("-", 1)[-1]
            if not number.isdigit():
                raise QueryError(_("A key looks like KEY-12."))
            return self.simple(FIELD_TO_DB["key"], op, int(number))
        if field == "type":
            if value not in IssueType.values:
                raise QueryError(_("Unknown type “%(value)s”.") % {"value": value})
            return self.simple("issue_type", op, value)
        if field == "priority":
            if value not in Priority.values:
                raise QueryError(_("Unknown priority “%(value)s”.") % {"value": value})
            return self.simple("priority", op, value)
        if field == "status":
            return self.simple("status", op, value)
        if field == "title":
            return self.contains("title__icontains", op, value)
        if field == "text":
            if op in ("~", "!~"):
                q = Q(title__icontains=value) | Q(description__icontains=value)
                return q if op == "~" else ~q
            raise QueryError(_("text supports ~ and !~ only."))
        if field in DATE_FIELDS:
            return self.date(FIELD_TO_DB[field], op, value)
        if field == "assignee" or field == "reporter":
            rel = field
            if op in ("=", "!="):
                q = Q(**{f"{rel}__username__iexact": value}) | Q(**{f"{rel}__email__iexact": value})
                return q if op == "=" else ~q
            raise QueryError(_("%(field)s supports = and != only.") % {"field": field})
        if field == "epic":
            number = value.rsplit("-", 1)[-1]
            if not number.isdigit():
                raise QueryError(_("An epic looks like KEY-12."))
            return self.simple("epic__number", op, int(number))
        relation = {"label": "labels__name", "component": "components__name", "version": "fix_versions__name",
                    "sprint": "sprint__name"}[field]
        if op in ("=", "!="):
            q = Q(**{f"{relation}__iexact": value})
            return q if op == "=" else ~q
        if op in ("~", "!~"):
            q = Q(**{f"{relation}__icontains": value})
            return q if op == "~" else ~q
        raise QueryError(_("%(field)s does not support %(op)s.") % {"field": field, "op": op})

    def simple(self, column, op, value):
        if op == "=":
            return Q(**{column: value})
        if op == "!=":
            return ~Q(**{column: value})
        raise QueryError(_("%(column)s supports = and != only.") % {"column": column})

    def contains(self, lookup, op, value):
        if op == "~":
            return Q(**{lookup: value})
        if op == "!~":
            return ~Q(**{lookup: value})
        raise QueryError(_("This field supports ~ and !~ only."))

    def date(self, column, op, value):
        try:
            day = datetime.date.fromisoformat(value)
        except ValueError:
            raise QueryError(_("“%(value)s” is not a date (use YYYY-MM-DD).") % {"value": value})
        suffix = {"=": "", "<": "__lt", ">": "__gt", "<=": "__lte", ">=": "__gte"}
        if op not in suffix and op != "!=":
            raise QueryError(_("Dates support = != < > <= >=, not %(op)s.") % {"op": op})
        # created_at and updated_at are timestamps: compare their date part. due_date is already a date.
        lookup = f"{column}__date" if column.endswith("_at") else column
        if op == "!=":
            return ~Q(**{lookup: day})
        return Q(**{f"{lookup}{suffix[op]}": day})


def parse(text, project, user):
    """Returns (Q for Issue querysets, ordering list such as ['-updated_at', 'number']) or raises QueryError."""
    text = (text or "").strip()
    order = []
    if not text:
        return Q(), order
    match = re.search(r"(?:^|\s+)ORDER\s+BY\s+", text, re.IGNORECASE)
    if match:
        order_text = text[match.end():]
        text = text[:match.start()]
        for part in order_text.split(","):
            words = part.split()
            if not words or len(words) > 2:
                raise QueryError(_("ORDER BY takes a field and optionally ASC or DESC."))
            field = words[0].lower()
            if field not in ORDERABLE:
                raise QueryError(_("Cannot order by “%(field)s”.") % {"field": field})
            direction = words[1].upper() if len(words) == 2 else "ASC"
            if direction not in ("ASC", "DESC"):
                raise QueryError(_("Use ASC or DESC."))
            column = FIELD_TO_DB.get(field, field)
            order.append(f"-{column}" if direction == "DESC" else column)
    tokens = tokenize(text)
    if not tokens:
        return Q(), order
    parser = Parser(tokens, project, user)
    q = parser.or_expr()
    if parser.i != len(tokens):
        raise QueryError(_("Something after the end of the query is not understood."))
    return q, order
