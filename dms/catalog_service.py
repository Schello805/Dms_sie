"""Transaction boundary for every document mutation; all SQL uses bound parameters."""
from .audit_text import optional_reason
import hashlib
import json
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone
from .catalog_columns import CATALOG_SORTS


from . import services as s

def visible_versions(user, search='', status='', department='', standard='', due_only=False, current_only=False, limit=200, catalog_only=False, offset=0, sort='', direction='asc'):
    uid = s.actor(user) if user.is_authenticated else None
    search = search.strip()[:200]
    pattern = '%' + search + '%'
    if catalog_only and status not in ('','DRAFT','APPROVED'):
        return []
    # SQL identifiers and direction come exclusively from this allowlist.
    ordering = (CATALOG_SORTS[sort] + (' DESC' if direction=='desc' else ' ASC') +
        ' NULLS LAST,d.number,v.major DESC,v.minor DESC,v.id') if sort in CATALOG_SORTS else 'COALESCE(matched.score,0) DESC,d.number,v.major DESC,v.minor DESC,v.id'
    rows = s.query("""WITH input AS (
            SELECT CASE WHEN %s='' THEN NULL::tsquery ELSE websearch_to_tsquery('german',%s) END AS terms
        ) SELECT v.*,count(*) OVER() AS total_count,(SELECT '/d/'||l.kind_slug||'/'||l.number_slug||'/' FROM document_links l WHERE l.document_id=d.id) AS stable_path,d.number,dep.name AS department,(SELECT display_name FROM users WHERE id=d.owner_id) AS author_name,
        review.review_due_on,review.last_review_on,
        (SELECT uploaded_at FROM document_upload_origins WHERE document_id=v.document_id) AS uploaded_at,
        (SELECT coalesce(rv.approved_at,(SELECT max(a.decided_at) FROM approval_decisions a WHERE a.version_id=v.id AND a.stage='APPROVAL' AND a.decision='ACCEPT')) FROM document_versions ignored LEFT JOIN release_validity rv ON rv.version_id=ignored.id WHERE ignored.id=v.id) AS approved_at,
        (v.id=current_release(v.document_id)) AS is_current,
        coalesce(c.display_name,c.name) AS category_name,
        preferred.file_id AS reading_file_id,preferred.original_name AS reading_file_name,
        review.review_result,matched.snippet,matched.original_name AS matched_file,
        (SELECT max(a.decided_at) FROM approval_decisions a WHERE a.version_id=v.id AND a.stage='APPROVAL' AND a.decision='ACCEPT') AS released_at,
        (EXISTS (SELECT 1 FROM document_withdrawals dw WHERE dw.document_id=v.document_id)
            AND current_release(v.document_id) IS NULL) AS document_withdrawn
        FROM document_versions v CROSS JOIN input
        JOIN documents d ON d.id=v.document_id
        JOIN departments dep ON dep.id=d.responsible_department_id
        JOIN document_categories c ON c.name=d.document_type
        JOIN version_review_status review ON review.version_id=v.id
        LEFT JOIN LATERAL (SELECT f.id AS file_id,f.original_name FROM version_files vf JOIN file_objects f ON f.id=vf.file_id
            WHERE vf.version_id=v.id ORDER BY CASE WHEN vf.purpose='RELEASE' THEN 0 WHEN lower(f.original_name) LIKE '%%.pdf' THEN 1 WHEN lower(f.original_name) LIKE '%%.txt' THEN 2 ELSE 3 END,f.id LIMIT 1) preferred ON true
        LEFT JOIN LATERAL (
            SELECT i.file_id,f.original_name,ts_rank_cd(i.search_vector,input.terms) AS score,
                left(ts_headline('german',i.text_content,input.terms,
                    'StartSel=__IMS_HIT_START__, StopSel=__IMS_HIT_END__, MaxWords=35, MinWords=10, MaxFragments=1'),600) AS snippet
            FROM version_files vf JOIN file_text_indexes i ON i.file_id=vf.file_id
            JOIN file_objects f ON f.id=vf.file_id
            WHERE vf.version_id=v.id AND (can_read_version(%s,v.id) OR (v.status='APPROVED' AND NOT d.login_required AND v.id=current_release(v.document_id)))
                AND i.status='READY' AND i.search_vector @@ input.terms
            ORDER BY score DESC,i.file_id LIMIT 1
        ) matched ON true
        WHERE d.active AND (can_read_version(%s,v.id) OR (v.status='APPROVED' AND NOT d.login_required AND v.id=current_release(v.document_id)))
        AND (%s='' OR v.title ILIKE %s OR d.number ILIKE %s OR matched.file_id IS NOT NULL OR EXISTS(SELECT 1 FROM version_distribution dist WHERE dist.version_id=v.id AND dist.keywords ILIKE %s))
        AND (%s='' OR v.status=%s OR (%s AND %s='DRAFT' AND v.status IN ('IN_REVIEW','PENDING_APPROVAL')))
        AND (NOT %s OR (
            (v.status='APPROVED' AND v.id=current_release(v.document_id))
            OR (v.status IN ('DRAFT','IN_REVIEW','PENDING_APPROVAL') AND (v.created_by=%s OR d.owner_id=%s)
                AND has_role(%s,'AUTHOR',d.responsible_department_id,d.id))))
        AND (%s='' OR dep.id::text=%s)
        AND (%s='' OR EXISTS (SELECT 1 FROM version_standard_links vl
            JOIN standard_references sr ON sr.id=vl.reference_id
            WHERE vl.version_id=v.id AND sr.standard_id::text=%s))
        AND (NOT %s OR (v.id=current_release(v.document_id)
           
            AND (review.review_due_on<=%s
                OR review.review_result IN ('REVISION_REQUIRED','WITHDRAWAL_REQUIRED'))))
        AND (NOT %s OR (v.id=current_release(v.document_id) AND v.status='APPROVED'))
        ORDER BY """ + ordering + """ LIMIT %s OFFSET %s""",
        [search,search,uid,uid,search,pattern,pattern,pattern,status,status,catalog_only,status,catalog_only,uid,uid,uid,department,department,
         standard,standard,due_only,timezone.localdate(),current_only,min(max(int(limit),1),5000),max(int(offset),0)])
    for row in rows:
        from pathlib import Path
        row['previewable'] = bool(row['reading_file_name'] and Path(row['reading_file_name']).suffix.lower() in ('.pdf','.txt'))
        row['review_overdue'] = bool(row['is_current'] and row['review_due_on'] and row['review_due_on']<timezone.localdate())
    return rows
