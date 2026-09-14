// DealChatView.swift — чат покупателя и продавца места в очереди.
// После оплаты стороны договариваются здесь: куда подойти, как узнать друг
// друга, когда подмениться. Доступ имеют только участники сделки.
import SwiftUI

@MainActor
final class DealChatViewModel: ObservableObject {
    @Published var messages: [DealMessageDTO] = []
    @Published var draft = ""
    @Published var isSending = false
    @Published var error: String?

    let transferId: Int
    let myUserId: Int
    private var lastLoadedId = 0
    private var pollTask: Task<Void, Never>?

    init(transferId: Int, myUserId: Int) {
        self.transferId = transferId
        self.myUserId = myUserId
    }

    func startPolling() {
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.loadNew()
                try? await Task.sleep(for: .seconds(4))
            }
        }
    }

    func stopPolling() {
        pollTask?.cancel()
        pollTask = nil
    }

    func loadNew() async {
        do {
            let fresh: [DealMessageDTO] = try await APIClient.shared.request(
                "GET", "transfers/\(transferId)/messages?after_id=\(lastLoadedId)",
                as: [DealMessageDTO].self)
            if !fresh.isEmpty {
                messages.append(contentsOf: fresh)
                lastLoadedId = fresh.map(\.id).max() ?? lastLoadedId
            }
            error = nil
        } catch {
            if case let APIError.server(code, _, status) = error, status == 403 {
                self.error = "Чат доступен только участникам сделки"
            } else if case APIError.unauthorized = error {
                // session expired — AuthManager handles logout
            } else {
                // оффлайн — оставляем уже загруженные сообщения (43)
                self.error = "Нет соединения — сообщения могут устареть"
            }
        }
    }

    func send() async {
        let body = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !body.isEmpty, !isSending else { return }
        isSending = true
        defer { isSending = false }
        do {
            let sent: DealMessageDTO = try await APIClient.shared.request(
                "POST", "transfers/\(transferId)/messages",
                body: ["body": AnyEncodable(body)],
                as: DealMessageDTO.self)
            messages.append(sent)
            lastLoadedId = max(lastLoadedId, sent.id)
            draft = ""
            error = nil
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? "Не удалось отправить"
        }
    }
}

struct DealChatView: View {
    @StateObject private var model: DealChatViewModel
    @EnvironmentObject var auth: AuthManager

    init(transferId: Int, myUserId: Int) {
        _model = StateObject(wrappedValue: DealChatViewModel(
            transferId: transferId, myUserId: myUserId))
    }

    var body: some View {
        VStack(spacing: 0) {
            if let error = model.error, model.messages.isEmpty {
                ContentUnavailableView("Чат недоступен",
                                       systemImage: "exclamationmark.bubble",
                                       description: Text(error))
            } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(spacing: 8) {
                            ForEach(model.messages) { message in
                                bubble(message)
                                    .id(message.id)
                            }
                        }
                        .padding()
                    }
                    .onChange(of: model.messages.count) {
                        if let last = model.messages.last {
                            withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                        }
                    }
                }
            }
            if let error = model.error, !model.messages.isEmpty {
                Text(error)
                    .font(.caption2).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 2)
                    .background(.orange.opacity(0.1))
            }
            inputBar
        }
        .navigationTitle("Чат по сделке")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .principal) {
                VStack(spacing: 0) {
                    Text("Чат по сделке").font(.headline)
                    Text("Договоритесь, где подойти и как узнать друг друга")
                        .font(.caption2).foregroundStyle(.secondary)
                }
            }
        }
        .task {
            await model.loadNew()
            model.startPolling()
        }
        .onDisappear { model.stopPolling() }
    }

    private func bubble(_ message: DealMessageDTO) -> some View {
        let isMine = message.senderUserId == model.myUserId
        return HStack {
            if isMine { Spacer(minLength: 48) }
            VStack(alignment: isMine ? .trailing : .leading, spacing: 4) {
                Text(message.body)
                    .textSelection(.enabled)
                if let date = message.createdAt {
                    Text(date.formatted(.dateTime.hour().minute()))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(12)
            .background(RoundedRectangle(cornerRadius: 16)
                .fill(isMine ? Color.blue.opacity(0.15) : Color(.secondarySystemBackground)))
            if !isMine { Spacer(minLength: 48) }
        }
        .accessibilityLabel(isMine ? "Моё сообщение" : "Сообщение собеседника")
    }

    private var inputBar: some View {
        HStack(spacing: 8) {
            TextField("Куда подойти? Как вас узнать?", text: $model.draft, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(1...4)
                .onSubmit { Task { await model.send() } }
            Button {
                Task { await model.send() }
            } label: {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.title2)
            }
            .disabled(model.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                      || model.isSending)
        }
        .padding(12)
        .background(.ultraThinMaterial)
    }
}
