"""gsuite — school Google account tools sharing one Chrome session.

The school blocks OAuth client creation, so these drive the browser profile
that is already signed in as the school account. That profile, the identity
guard and the CDP driver all come from the `classroom` package; this adds the
services: mail, drive/docs, calendar.
"""

__version__ = "0.1.0"
