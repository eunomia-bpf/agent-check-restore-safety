package main

import (
	"bufio"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/control"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/gateway"
	"github.com/eunomia-bpf/agent-check-restore-safety/runtime/internal/kernel"
)

type sinkRecord struct {
	ID          string `json:"id"`
	RequestHash string `json:"request_hash"`
	Result      string `json:"result"`
}

type paymentSink struct {
	mu         sync.Mutex
	file       *os.File
	records    map[string]sinkRecord
	dropFirst  bool
	deliveries int
	commits    int
}

func openPaymentSink(path string) (*paymentSink, error) {
	file, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR|os.O_APPEND, 0o600)
	if err != nil {
		return nil, err
	}
	sink := &paymentSink{file: file, records: make(map[string]sinkRecord), dropFirst: true}
	if _, err := file.Seek(0, io.SeekStart); err != nil {
		file.Close()
		return nil, err
	}
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		var record sinkRecord
		if err := json.Unmarshal(scanner.Bytes(), &record); err != nil {
			file.Close()
			return nil, fmt.Errorf("decode payment record: %w", err)
		}
		if prior, ok := sink.records[record.ID]; ok && prior != record {
			file.Close()
			return nil, fmt.Errorf("payment identity %q has conflicting durable records", record.ID)
		}
		sink.records[record.ID] = record
	}
	if err := scanner.Err(); err != nil {
		file.Close()
		return nil, err
	}
	if len(sink.records) != 0 {
		sink.dropFirst = false
	}
	_, err = file.Seek(0, io.SeekEnd)
	return sink, err
}

func (s *paymentSink) Close() error { return s.file.Close() }

func (s *paymentSink) ServeHTTP(writer http.ResponseWriter, request *http.Request) {
	body, err := io.ReadAll(io.LimitReader(request.Body, 1<<20))
	if err != nil {
		http.Error(writer, err.Error(), http.StatusBadRequest)
		return
	}
	id := request.Header.Get("X-Operation-ID")
	hashBytes := sha256.Sum256(body)
	requestHash := hex.EncodeToString(hashBytes[:])

	s.mu.Lock()
	defer s.mu.Unlock()
	s.deliveries++
	record, exists := s.records[id]
	if exists && record.RequestHash != requestHash {
		http.Error(writer, "operation identity conflict", http.StatusConflict)
		return
	}
	if !exists {
		record = sinkRecord{ID: id, RequestHash: requestHash, Result: "charged-once"}
		encoded, _ := json.Marshal(record)
		if _, err := s.file.Write(append(encoded, '\n')); err != nil {
			http.Error(writer, err.Error(), http.StatusInternalServerError)
			return
		}
		if err := s.file.Sync(); err != nil {
			http.Error(writer, err.Error(), http.StatusInternalServerError)
			return
		}
		s.records[id] = record
		s.commits++
		if s.dropFirst {
			s.dropFirst = false
			hijacker, ok := writer.(http.Hijacker)
			if !ok {
				http.Error(writer, "cannot simulate lost response", http.StatusInternalServerError)
				return
			}
			connection, _, err := hijacker.Hijack()
			if err == nil {
				_ = connection.Close()
			}
			return
		}
	}
	writer.Header().Set("X-Remote-Operation", id)
	writer.Header().Set("Content-Type", "application/json")
	resultHash := sha256.Sum256([]byte(record.Result))
	_ = json.NewEncoder(writer).Encode(map[string]any{
		"schema":           1,
		"operation_id":     id,
		"outcome":          kernel.Succeeded,
		"result_hash":      hex.EncodeToString(resultHash[:]),
		"remote_reference": id,
	})
}

func requirement(id, target string) kernel.Requirement {
	return kernel.Requirement{
		ID:         id,
		Results:    map[string]uint32{"invoice-paid": 1},
		Capacities: map[string]uint32{"spend": 1},
		Kinds: map[string]kernel.KindSpec{
			"charge-invoice": {
				Costs:              map[string]uint32{"spend": 1},
				Produces:           map[string]uint32{"invoice-paid": 1},
				RetrySafe:          true,
				Target:             target,
				Method:             http.MethodPost,
				ResponseClassifier: gateway.ResponseReceiptV1,
			},
			"send-tip": {
				Costs:    map[string]uint32{"spend": 1},
				Produces: map[string]uint32{"tip-sent": 1},
			},
		},
	}
}

func main() {
	var historyPath string
	var sinkPath string
	flag.StringVar(&historyPath, "history", "", "path for the durable runtime history")
	flag.StringVar(&sinkPath, "sink", "", "path for the independent payment record")
	flag.Parse()
	if historyPath == "" || sinkPath == "" {
		directory, err := os.MkdirTemp("", "running-change-demo-")
		if err != nil {
			log.Fatal(err)
		}
		if historyPath == "" {
			historyPath = filepath.Join(directory, "runtime.history")
		}
		if sinkPath == "" {
			sinkPath = filepath.Join(directory, "payment.history")
		}
	}

	sink, err := openPaymentSink(sinkPath)
	if err != nil {
		log.Fatal(err)
	}
	defer sink.Close()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		log.Fatal(err)
	}
	server := &http.Server{Handler: sink, ReadHeaderTimeout: 2 * time.Second}
	go func() {
		if err := server.Serve(listener); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Printf("payment service: %v", err)
		}
	}()
	defer server.Shutdown(context.Background())

	first, err := control.Open(historyPath)
	if err != nil {
		log.Fatal(err)
	}
	if first.Snapshot().Rule == nil {
		certificate, err := first.Compile(requirement("invoice-v1", "http://"+listener.Addr().String()))
		if err != nil {
			log.Fatal(err)
		}
		if err := first.Activate(certificate); err != nil {
			log.Fatal(err)
		}
	}
	stale, err := first.Compile(requirement("invoice-v2", "http://"+listener.Addr().String()))
	if err != nil {
		log.Fatal(err)
	}
	_, blockedTip := first.Prepare("tip-1", "agent", "send-tip", "tip-request")
	if blockedTip == nil {
		log.Fatal("tip unexpectedly passed the non-stranding rule")
	}
	firstGateway, _ := gateway.New(first, nil)
	request := gateway.Request{
		ID:     "invoice-charge-1",
		Domain: "microservice",
		Kind:   "charge-invoice",
		URL:    "http://" + listener.Addr().String(),
		Body:   []byte(`{"invoice":"A-17","amount":42}`),
	}
	firstOutcome, firstErr := firstGateway.Execute(context.Background(), request)
	if !errors.Is(firstErr, gateway.ErrOutcomeUnknown) && firstOutcome.Phase != kernel.Succeeded {
		log.Fatalf("first dispatch: outcome=%+v error=%v", firstOutcome, firstErr)
	}
	if err := first.Close(); err != nil {
		log.Fatal(err)
	}

	second, err := control.Open(historyPath)
	if err != nil {
		log.Fatal(err)
	}
	defer second.Close()
	secondGateway, _ := gateway.New(second, nil)
	finalOutcome := firstOutcome
	if firstOutcome.Phase != kernel.Succeeded {
		finalOutcome, err = secondGateway.Execute(context.Background(), request)
		if err != nil {
			log.Fatal(err)
		}
	}
	staleRejected := second.Activate(stale) != nil

	sink.mu.Lock()
	deliveries := sink.deliveries
	commits := sink.commits
	sink.mu.Unlock()
	summary := map[string]any{
		"history":                    historyPath,
		"payment_record":             sinkPath,
		"blocked_stranding_action":   blockedTip != nil,
		"first_network_result":       firstOutcome.Phase,
		"recovered_result":           finalOutcome.Phase,
		"remote_deliveries":          deliveries,
		"remote_commits":             commits,
		"stale_certificate_rejected": staleRejected,
		"history_head":               second.Snapshot().History,
	}
	encoded, _ := json.MarshalIndent(summary, "", "  ")
	fmt.Println(string(encoded))
}
