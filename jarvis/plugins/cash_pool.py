"""
You can ask me to "show the cash pool" if you would like to see your debts. You
can also ask me to "show the cash pool history", if you'd prefer.
Alternatively, you may inform me that "Tom sent $42 to Dick" or that "Tom paid
$333 for Tom, Dick, and Harry".
"""
import contextlib
import re

from ..db import conn
from ..plugin import Plugin


DELIMITED = re.compile(r"[\w']+")


class CashPool(Plugin):
    @Plugin.on_message(r'.*explain.*cash pool.*')
    def explain(self, ch, _user, _groups):
        self.send(ch, __doc__.replace('\n', ' '))

    @Plugin.on_message(r'(.*cash pool.*history.*)')
    def show_history(self, ch, _user, groups):
        recent = -10
        if any('entire' in g for g in groups):
            recent = None

        with contextlib.closing(conn.cursor()) as cur:
            history = cur.execute(""" SELECT source, targets, value, reason
                                      FROM cash_pool_history
                                      ORDER BY created_at DESC
                                  """).fetchall()
            lookup = {k: v for k, v in cur.execute(
                """ SELECT uuid, first_name FROM user """).fetchall()}

        if not history:
            self.send(ch, 'I have no record of a cash pool, sir.')
        elif recent is None:
            self.send(ch, 'Very good, sir, displaying your history now:')
        else:
            self.send(ch, 'Very good, sir, displaying recent history now:')

        for item in history[recent:]:
            source, targets, value, reason = item
            targets = eval(targets)  # pylint: disable=W0123
            self.send(ch, '{} -> {}: ${} {}'.format(
                lookup[source], ' and '.join(lookup[k] for k in targets),
                value, reason))

    @Plugin.on_message(r'.*(display|show).*cash pool.*')
    def show_pool(self, ch, _user, _groups):
        self.send(ch, "I've analyzed your cash pool.")
        with contextlib.closing(conn.cursor()) as cur:
            data = cur.execute(""" SELECT first_name,
                                          CAST(cad AS FLOAT) / 100,
                                          CAST(usd AS FLOAT) / 100
                                   FROM cash_pool
                                   INNER JOIN user
                                       ON user.uuid = cash_pool.uuid
                                   WHERE cad <> 0 OR usd <> 0
                                   ORDER BY first_name ASC
                               """).fetchall()

        for first_name, cad, usd in data:
            if cad:
                self.send(ch, '{} {} ${}{}'.format(
                    first_name.title(), 'owes' if cad > 0 else 'is owed',
                    abs(cad), ' CAD' if usd else ''))
            if usd:
                self.send(ch, '{} {} ${} USD'.format(
                    first_name.title(), 'owes' if usd > 0 else 'is owed',
                    abs(usd)))

        if not data:
            self.send(ch, 'All appears to be settled.')

    @Plugin.on_message(r'(.*) (\w+) (sent|paid) \$([\d\.]+) (to|for) ([, \w]+)(\.)?')
    def send_cash(self, ch, user, groups):
        reason, single, _direction, value, _, multiple, _ = groups
        value = int(float(value) * 100)

        with contextlib.closing(conn.cursor()) as cur:
            if single == 'i':
                s = user
            else:
                s = cur.execute(""" SELECT uuid
                                    FROM user
                                    WHERE first_name = ?
                                """, [single]).fetchone()[0]

            m = filter(lambda u: u != 'and',
                       re.findall(DELIMITED, multiple))
            for idx, item in enumerate(m):
                if item == 'me':
                    m[idx] = user
                elif item in ('herself', 'himself'):
                    m[idx] = s
                else:
                    m[idx] = cur.execute(""" SELECT uuid
                                             FROM user
                                             WHERE first_name = ?
                                         """, [item]).fetchone()[0]

            cur.execute(""" UPDATE cash_pool
                            SET cad = cad - ?
                            WHERE uuid = ?
                        """, [value, s])
            m_value = int(round(value / len(m)))
            for p in m:
                cur.execute(""" UPDATE cash_pool
                                SET cad = cad + ?
                                WHERE uuid = ?
                            """, [m_value, p])

            cur.execute(""" INSERT INTO cash_pool_history (source, targets,
                                                           value, reason)
                            VALUES (?, ?, ?, ?)
                        """, [s, str(m), value, reason[7:].strip()])
            conn.commit()

        self.send(ch, 'Very good, sir.')