// Package postgresoutbox implements a provider adapter backed by a write-once
// PostgreSQL outbox row.
//
// The schema is deliberately not created by the Driver. Operators must apply
// migrations/001_create_safe_change_outbox.sql before opening the adapter.
package postgresoutbox

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/provideradapter"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	tableName         = "public.safe_change_outbox"
	factDomainV1      = "safe-change-postgres-outbox-fact-v1"
	remoteReferenceV1 = "postgres-outbox-v1:"
)

var (
	// ErrConflict means an Operation identity is already bound to different
	// public request bytes. It must be treated as unknown, never as a failed
	// external action.
	ErrConflict = errors.New("PostgreSQL outbox Operation conflicts with its durable row")
	// ErrCorruptRecord means a stored digest does not describe the stored row.
	// It must be treated as unknown, never as a failed external action.
	ErrCorruptRecord = errors.New("PostgreSQL outbox row failed its integrity check")
)

const connectionInvariantSQL = `
SELECT
    NOT pg_is_in_recovery(),
    current_setting('fsync') = 'on',
    current_setting('full_page_writes') = 'on',
    EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS class
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = class.relnamespace
        WHERE namespace.nspname = 'public'
          AND class.relname = 'safe_change_outbox'
          AND class.relkind = 'r'
          AND class.relpersistence = 'p'
    )`

const insertSQL = `
INSERT INTO public.safe_change_outbox
    (operation_id, content_type, body, body_hash, fact_hash)
VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (operation_id) DO NOTHING
RETURNING operation_id, content_type, body, body_hash, fact_hash`

const selectSQL = `
SELECT operation_id, content_type, body, body_hash, fact_hash
FROM public.safe_change_outbox
WHERE operation_id = $1`

type record struct {
	operationID string
	contentType string
	body        []byte
	bodyHash    string
	factHash    string
}

type rowScanner interface {
	Scan(...any) error
}

type connectionQuerier interface {
	QueryRow(context.Context, string, ...any) pgx.Row
}

type executeTransaction interface {
	setSynchronousCommit(context.Context) error
	insert(context.Context, record) (record, bool, error)
	lookup(context.Context, string) (record, error)
	commit(context.Context) error
	rollback(context.Context) error
}

type database interface {
	beginExecute(context.Context) (executeTransaction, error)
	lookup(context.Context, string) (record, error)
	close()
}

// Driver implements provideradapter.Driver with a pgx connection pool. A
// successful result means the exact Operation row committed durably in the
// fixed PostgreSQL outbox table.
type Driver struct {
	database database
}

var _ provideradapter.Driver = (*Driver)(nil)

// Open creates and validates a pooled Driver. Every physical connection is
// rejected unless it reaches a primary with fsync and full_page_writes enabled
// and the supplied outbox migration has created a permanent ordinary table.
func Open(ctx context.Context, dsn string) (*Driver, error) {
	if ctx == nil {
		return nil, errors.New("PostgreSQL outbox context is nil")
	}
	if strings.TrimSpace(dsn) == "" {
		return nil, errors.New("PostgreSQL outbox DSN is empty")
	}
	config, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		// Parse errors can quote their input. Do not propagate a private DSN.
		return nil, errors.New("PostgreSQL outbox DSN is invalid")
	}
	config.AfterConnect = func(connectCtx context.Context, connection *pgx.Conn) error {
		return validatePhysicalConnection(connectCtx, connection)
	}
	pool, err := pgxpool.NewWithConfig(ctx, config)
	if err != nil {
		return nil, errors.New("could not create PostgreSQL outbox connection pool")
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("could not validate PostgreSQL outbox connection: %w", err)
	}
	return &Driver{database: &poolDatabase{pool: pool}}, nil
}

// Close releases all pooled PostgreSQL connections.
func (driver *Driver) Close() {
	if driver != nil && driver.database != nil {
		driver.database.close()
	}
}

// Execute inserts the exact Operation row, or proves that an identical row
// already exists. It never reports a provider-level Failed outcome.
func (driver *Driver) Execute(ctx context.Context, effect provideradapter.Effect) (provideradapter.Result, error) {
	if driver == nil || driver.database == nil {
		return provideradapter.Result{}, errors.New("PostgreSQL outbox Driver is closed or uninitialized")
	}
	if ctx == nil {
		return provideradapter.Result{}, errors.New("PostgreSQL outbox Execute context is nil")
	}
	if effect.IdempotencyKey != effect.OperationID {
		return provideradapter.Result{}, errors.New("PostgreSQL outbox idempotency identity does not match the Operation")
	}
	expected, err := recordFor(effect.OperationID, effect.ContentType, effect.Body)
	if err != nil {
		return provideradapter.Result{}, err
	}

	transaction, err := driver.database.beginExecute(ctx)
	if err != nil {
		return provideradapter.Result{}, fmt.Errorf("begin PostgreSQL outbox transaction: %w", err)
	}
	committed := false
	defer func() {
		if !committed {
			rollbackCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			_ = transaction.rollback(rollbackCtx)
		}
	}()

	if err := transaction.setSynchronousCommit(ctx); err != nil {
		return provideradapter.Result{}, fmt.Errorf("enable synchronous PostgreSQL outbox commit: %w", err)
	}
	stored, inserted, err := transaction.insert(ctx, expected)
	if err != nil {
		return provideradapter.Result{}, fmt.Errorf("insert PostgreSQL outbox row: %w", err)
	}
	if !inserted {
		// This must be a second statement. Under READ COMMITTED it receives a
		// new snapshot after ON CONFLICT waited for a concurrent inserter.
		stored, err = transaction.lookup(ctx, expected.operationID)
		if err != nil {
			return provideradapter.Result{}, fmt.Errorf("read conflicting PostgreSQL outbox row: %w", err)
		}
	}
	if err := compareRecord(stored, expected); err != nil {
		return provideradapter.Result{}, err
	}
	if err := transaction.commit(ctx); err != nil {
		return provideradapter.Result{}, fmt.Errorf("commit PostgreSQL outbox transaction: %w", err)
	}
	committed = true
	return successResult(expected), nil
}

// Observe returns Inconclusive when no durable row exists. Conflicting or
// corrupt rows return an error so the runtime cannot mistake uncertainty for
// a provider-level failure.
func (driver *Driver) Observe(ctx context.Context, query provideradapter.Query) (provideradapter.Result, error) {
	if driver == nil || driver.database == nil {
		return provideradapter.Result{}, errors.New("PostgreSQL outbox Driver is closed or uninitialized")
	}
	if ctx == nil {
		return provideradapter.Result{}, errors.New("PostgreSQL outbox Observe context is nil")
	}
	if !canonicalSHA256(query.RequestHash) {
		return provideradapter.Result{}, errors.New("PostgreSQL outbox observation request hash is invalid")
	}
	expected, err := recordFor(query.OperationID, query.ContentType, query.Body)
	if err != nil {
		return provideradapter.Result{}, err
	}
	stored, err := driver.database.lookup(ctx, query.OperationID)
	if errors.Is(err, pgx.ErrNoRows) {
		return provideradapter.Result{Outcome: provideradapter.Inconclusive}, nil
	}
	if err != nil {
		return provideradapter.Result{}, fmt.Errorf("observe PostgreSQL outbox row: %w", err)
	}
	if err := compareRecord(stored, expected); err != nil {
		return provideradapter.Result{}, err
	}
	return successResult(expected), nil
}

// FactHash returns the lowercase SHA-256 digest of a versioned, length-framed
// encoding of OperationID, ContentType, and Body. Execute and Observe use this
// same function, so direct and query paths identify exactly the same fact.
func FactHash(operationID, contentType string, body []byte) string {
	hash := sha256.New()
	writeFrame(hash, []byte(factDomainV1))
	writeFrame(hash, []byte(operationID))
	writeFrame(hash, []byte(contentType))
	writeFrame(hash, body)
	return hex.EncodeToString(hash.Sum(nil))
}

type byteWriter interface {
	Write([]byte) (int, error)
}

func writeFrame(destination byteWriter, value []byte) {
	var length [8]byte
	binary.BigEndian.PutUint64(length[:], uint64(len(value)))
	_, _ = destination.Write(length[:])
	_, _ = destination.Write(value)
}

func recordFor(operationID, contentType string, body []byte) (record, error) {
	if !canonicalOperationID(operationID) {
		return record{}, errors.New("PostgreSQL outbox Operation identity is invalid")
	}
	if len(contentType) > 1024 || strings.ContainsRune(contentType, '\x00') {
		return record{}, errors.New("PostgreSQL outbox Content-Type is invalid")
	}
	if int64(len(body)) > provideradapter.MaxRequestBytes {
		return record{}, errors.New("PostgreSQL outbox body exceeds the runtime request limit")
	}
	ownedBody := make([]byte, len(body))
	copy(ownedBody, body)
	bodyDigest := sha256.Sum256(ownedBody)
	return record{
		operationID: operationID,
		contentType: contentType,
		body:        ownedBody,
		bodyHash:    hex.EncodeToString(bodyDigest[:]),
		factHash:    FactHash(operationID, contentType, ownedBody),
	}, nil
}

func compareRecord(stored, expected record) error {
	bodyDigest := sha256.Sum256(stored.body)
	if stored.bodyHash != hex.EncodeToString(bodyDigest[:]) ||
		stored.factHash != FactHash(stored.operationID, stored.contentType, stored.body) {
		return ErrCorruptRecord
	}
	if stored.operationID != expected.operationID ||
		stored.contentType != expected.contentType ||
		!bytes.Equal(stored.body, expected.body) ||
		stored.bodyHash != expected.bodyHash ||
		stored.factHash != expected.factHash {
		return ErrConflict
	}
	return nil
}

func successResult(value record) provideradapter.Result {
	return provideradapter.Result{
		Outcome:         provideradapter.Succeeded,
		FactHash:        value.factHash,
		RemoteReference: remoteReferenceV1 + value.operationID,
	}
}

func canonicalOperationID(value string) bool {
	if !strings.HasPrefix(value, "op-") || len(value) != len("op-")+sha256.Size*2 {
		return false
	}
	digest := strings.TrimPrefix(value, "op-")
	return canonicalSHA256(digest)
}

func canonicalSHA256(value string) bool {
	if len(value) != sha256.Size*2 {
		return false
	}
	decoded, err := hex.DecodeString(value)
	return err == nil && len(decoded) == sha256.Size && hex.EncodeToString(decoded) == value
}

func validatePhysicalConnection(ctx context.Context, connection connectionQuerier) error {
	var primary, fsync, fullPageWrites, permanentTable bool
	if err := connection.QueryRow(ctx, connectionInvariantSQL).Scan(
		&primary, &fsync, &fullPageWrites, &permanentTable,
	); err != nil {
		return fmt.Errorf("check PostgreSQL outbox connection invariants: %w", err)
	}
	if !primary {
		return errors.New("PostgreSQL outbox requires a writable primary")
	}
	if !fsync {
		return errors.New("PostgreSQL outbox requires fsync=on")
	}
	if !fullPageWrites {
		return errors.New("PostgreSQL outbox requires full_page_writes=on")
	}
	if !permanentTable {
		return errors.New("PostgreSQL outbox requires the permanent public.safe_change_outbox table")
	}
	return nil
}

type poolDatabase struct {
	pool *pgxpool.Pool
}

func (database *poolDatabase) beginExecute(ctx context.Context) (executeTransaction, error) {
	transaction, err := database.pool.BeginTx(ctx, pgx.TxOptions{
		IsoLevel:   pgx.ReadCommitted,
		AccessMode: pgx.ReadWrite,
	})
	if err != nil {
		return nil, err
	}
	return &pgxExecuteTransaction{transaction: transaction}, nil
}

func (database *poolDatabase) lookup(ctx context.Context, operationID string) (record, error) {
	return scanRecord(database.pool.QueryRow(ctx, selectSQL, operationID))
}

func (database *poolDatabase) close() {
	database.pool.Close()
}

type pgxExecuteTransaction struct {
	transaction pgx.Tx
}

func (transaction *pgxExecuteTransaction) setSynchronousCommit(ctx context.Context) error {
	_, err := transaction.transaction.Exec(ctx, "SET LOCAL synchronous_commit = on")
	return err
}

func (transaction *pgxExecuteTransaction) insert(ctx context.Context, value record) (record, bool, error) {
	stored, err := scanRecord(transaction.transaction.QueryRow(
		ctx, insertSQL, value.operationID, value.contentType, value.body, value.bodyHash, value.factHash,
	))
	if errors.Is(err, pgx.ErrNoRows) {
		return record{}, false, nil
	}
	return stored, err == nil, err
}

func (transaction *pgxExecuteTransaction) lookup(ctx context.Context, operationID string) (record, error) {
	return scanRecord(transaction.transaction.QueryRow(ctx, selectSQL, operationID))
}

func (transaction *pgxExecuteTransaction) commit(ctx context.Context) error {
	return transaction.transaction.Commit(ctx)
}

func (transaction *pgxExecuteTransaction) rollback(ctx context.Context) error {
	return transaction.transaction.Rollback(ctx)
}

func scanRecord(row rowScanner) (record, error) {
	var value record
	err := row.Scan(&value.operationID, &value.contentType, &value.body, &value.bodyHash, &value.factHash)
	return value, err
}
