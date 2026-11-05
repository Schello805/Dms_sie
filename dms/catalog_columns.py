"""Single source for sortable catalogue headings and trusted SQL expressions."""
COLUMNS = (
    ('number', 'Dokumentnummer', 'd.number'),
    ('title', 'Dokument', 'v.title'),
    ('uploaded', 'Hochgeladen', 'uploaded_at'),
    ('approved', 'Freigabe', 'approved_at'),
    ('status', 'Status', "(CASE WHEN v.status='APPROVED' THEN 'Freigegeben' ELSE 'Entwurf' END)"),
    ('review', 'Letztes Review', 'review.last_review_on'),
    ('due', 'Gültig bis / Review fällig', 'review.review_due_on'),
)
CATALOG_SORTS = {key: expression for key, label, expression in COLUMNS}
