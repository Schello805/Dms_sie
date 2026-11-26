"""Single source for sortable catalogue headings and trusted SQL expressions."""
COLUMNS = (
    ('number', 'Dokumentnummer', 'd.number'),
    ('title', 'Dokument', 'v.title'),
    ('type', 'Dokumentenart', 'coalesce(c.display_name,c.name)'),
    ('author', 'Autor', '(SELECT display_name FROM users WHERE id=d.owner_id)'),
    ('uploaded', 'Hochgeladen', 'uploaded_at'),
    ('review', 'Letztes Review', 'review.last_review_on'),
    ('due', 'Gültig bis / Review fällig', 'review.review_due_on'),
)
CATALOG_SORTS = {key: expression for key, label, expression in COLUMNS}
