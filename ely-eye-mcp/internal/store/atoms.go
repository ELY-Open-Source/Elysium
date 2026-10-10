package store

import (
	"context"
	"database/sql"
	"errors"
	"strings"

	"git.zacharyzhang.com/ZacharyZhang-NY/ely-eye/ely-eye-mcp/internal/domain"
)

func (s *Store) FetchAtom(ctx context.Context, atomID string) (domain.Atom, error) {
	if strings.TrimSpace(atomID) == "" {
		return domain.Atom{}, errors.New("atom_id is required")
	}
	row := s.db.QueryRowContext(ctx, `
		SELECT atom_id, source_id, modality, source, ingested_at,
		       COALESCE(holder_id, ''), COALESCE(origin, ''), COALESCE(scenario, ''),
		       COALESCE(event_time, ''), text, COALESCE(image_ref, ''),
		       COALESCE(layout_json, ''), relations_json, trust_json, token_equivalent, metadata_json
		FROM v_atoms_current
		WHERE atom_id = ?`, atomID)
	atom, err := scanAtom(row)
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return domain.Atom{}, errors.New("atom not found")
		}
		return domain.Atom{}, err
	}
	return atom, nil
}

type atomScanner interface {
	Scan(dest ...any) error
}

func scanAtom(scanner atomScanner) (domain.Atom, error) {
	var atom domain.Atom
	var layout string
	var relations string
	var trust string
	var metadata string
	if err := scanner.Scan(
		&atom.AtomID,
		&atom.SourceID,
		&atom.Modality,
		&atom.Source,
		&atom.IngestedAt,
		&atom.HolderID,
		&atom.Origin,
		&atom.Scenario,
		&atom.EventTime,
		&atom.Text,
		&atom.ImageRef,
		&layout,
		&relations,
		&trust,
		&atom.TokenEquivalent,
		&metadata,
	); err != nil {
		return domain.Atom{}, err
	}
	var err error
	atom.Layout, err = optionalJSONValue(layout)
	if err != nil {
		return domain.Atom{}, err
	}
	atom.Relations, err = requiredJSONValue(relations)
	if err != nil {
		return domain.Atom{}, err
	}
	atom.Trust, err = requiredJSONValue(trust)
	if err != nil {
		return domain.Atom{}, err
	}
	atom.Metadata, err = requiredJSONValue(metadata)
	if err != nil {
		return domain.Atom{}, err
	}
	return atom, nil
}
