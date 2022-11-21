# icsbusyer

This project reads an ICS file and parses it for busy status which it can then publish to a busy light running https://github.com/estruyf/unicorn-busy-server . As currently written it's tightly bound to a Microsoft Office 365 ICS feed, testing against the 'X-MICROSOFT-CDO-BUSYSTATUS' field for value 'BUSY' as event validation.

Current screaming TODOs:
* Test across days
* cache calendar feed
* eliminate full-day busy events
* parameterize timezone
