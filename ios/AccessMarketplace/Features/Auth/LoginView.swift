// LoginView.swift — экраны входа и профиля.
import SwiftUI

struct LoginView: View {
    @EnvironmentObject var auth: AuthManager
    @State private var mode: Mode = .login
    @State private var email = ""
    @State private var password = ""
    @State private var name = ""
    @State private var busy = false
    @FocusState private var focused: Field?

    enum Mode: String, CaseIterable {
        case login = "Вход"
        case register = "Регистрация"
    }

    enum Field { case email, password, name }

    var body: some View {
        NavigationStack {
            ZStack {
                // современный градиентный фон
                LinearGradient(
                    colors: [.indigo, .purple.opacity(0.8), .pink.opacity(0.6)],
                    startPoint: .topLeading, endPoint: .bottomTrailing)
                    .ignoresSafeArea()

                ScrollView {
                    VStack(spacing: 24) {
                        // логотип
                        VStack(spacing: 8) {
                            Image(systemName: "qrcode.circle.fill")
                                .font(.largeTitle)
                                .imageScale(.large)
                                .foregroundStyle(.white)
                                .accessibilityHidden(true)
                            Text("Маркет доступа")
                                .font(.title2.bold())
                                .foregroundStyle(.white)
                            Text("Очереди, билеты и слоты — в одном месте")
                                .font(.subheadline)
                                .foregroundStyle(.white.opacity(0.8))
                        }
                        .padding(.top, 32)

                        // карточка формы
                        VStack(spacing: 16) {
                            Picker("Режим", selection: $mode) {
                                ForEach(Mode.allCases, id: \.self) {
                                    Text($0.rawValue).tag($0)
                                }
                            }
                            .pickerStyle(.segmented)
                            .padding(.top, 16)

                            if mode == .register {
                                TextField("Имя", text: $name)
                                    .textFieldStyle(.plain)
                                    .focused($focused, equals: .name)
                                    .submitLabel(.next)
                                    .onSubmit { focused = .email }
                                    .padding(14)
                                    .background(RoundedRectangle(cornerRadius: 12)
                                        .fill(.quaternary.opacity(0.5)))
                            }

                            TextField("Email", text: $email)
                                .keyboardType(.emailAddress)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                                .focused($focused, equals: .email)
                                .submitLabel(.next)
                                .onSubmit { focused = .password }
                                .padding(14)
                                .background(RoundedRectangle(cornerRadius: 12)
                                    .fill(.quaternary.opacity(0.5)))

                            SecureField("Пароль (минимум 8 символов)", text: $password)
                                .focused($focused, equals: .password)
                                .submitLabel(.go)
                                .onSubmit { Task { await submit() } }
                                .padding(14)
                                .background(RoundedRectangle(cornerRadius: 12)
                                    .fill(.quaternary.opacity(0.5)))

                            Button {
                                Task { await submit() }
                            } label: {
                                Group {
                                    if busy {
                                        ProgressView().tint(.white)
                                    } else {
                                        Text(mode.rawValue)
                                            .font(.headline)
                                    }
                                }
                                .frame(maxWidth: .infinity)
                                .padding(14)
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(busy || email.isEmpty || password.count < 8)
                            .padding(.bottom, 16)
                        }
                        .padding(.horizontal, 20)
                        .background(RoundedRectangle(cornerRadius: 24)
                            .fill(.ultraThinMaterial))

                        if let error = auth.error {
                            Label(error, systemImage: "exclamationmark.circle.fill")
                                .font(.footnote)
                                .foregroundStyle(.white)
                                .padding(12)
                                .background(RoundedRectangle(cornerRadius: 12)
                                    .fill(.red.opacity(0.85)))
                        }

                        #if DEBUG
                        // тестовый аккаунт — только в дебаг-сборках:
                        // публикация живых кредов в релизе нарушает App Review
                        // Guideline 2.3.1
                        VStack(spacing: 4) {
                            Text("Тестовый аккаунт")
                                .font(.caption.bold())
                                .foregroundStyle(.white.opacity(0.7))
                            Text("demo@access.marketplace")
                                .font(.caption.monospaced())
                                .foregroundStyle(.white)
                            Text("Demo1234pass!")
                                .font(.caption.monospaced())
                                .foregroundStyle(.white.opacity(0.9))
                            Button("Заполнить автоматически") {
                                mode = .login
                                email = "demo@access.marketplace"
                                password = "Demo1234pass!"
                            }
                            .font(.caption.bold())
                            .buttonStyle(.bordered)
                            .tint(.white)
                            .padding(.top, 4)
                        }
                        .padding(.bottom, 24)
                        #endif
                    }
                    .padding(.horizontal, 20)
                }
            }
        }
    }

    private func submit() async {
        busy = true
        defer { busy = false }
        switch mode {
        case .login: await auth.login(email: email, password: password)
        case .register: await auth.register(email: email, password: password, name: name)
        }
    }
}

struct ProfileView: View {
    @EnvironmentObject var auth: AuthManager
    @State private var balance: WalletBalanceDTO?
    @State private var topupError: String?
    @State private var isToppingUp = false

    var body: some View {
        NavigationStack {
            List {
                Section("Кошелёк") {
                    HStack {
                        Label("Баланс", systemImage: "creditcard")
                        Spacer()
                        if let balance {
                            Text("\(balance.available) ₽")
                                .font(.title3.bold().monospacedDigit())
                        } else {
                            ProgressView()
                        }
                    }
                    if let balance, balance.escrow > 0 {
                        LabeledContent("В удержании по сделкам",
                                       value: "\(balance.escrow) ₽")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    Picker("Пополнить на", selection: $topupAmount) {
                        ForEach([500, 1000, 5000], id: \.self) { Text("\($0) ₽").tag($0) }
                    }
                    .pickerStyle(.segmented)
                    Button {
                        Task { await topup() }
                    } label: {
                        HStack {
                            Spacer()
                            if isToppingUp {
                                ProgressView()
                            } else {
                                Label("Пополнить (демо)", systemImage: "plus.circle.fill")
                                    .bold()
                            }
                            Spacer()
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(isToppingUp)
                    .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 8, trailing: 16))
                    if let topupError {
                        Label(topupError, systemImage: "exclamationmark.triangle.fill")
                            .font(.footnote).foregroundStyle(.red)
                    }
                    Text("Кошелёк используется для покупки мест. Оплата удерживается "
                         + "в escrow до подтверждения передачи.")
                        .font(.caption2).foregroundStyle(.secondary)
                }
                if let user = auth.user {
                    Section {
                        HStack(spacing: 16) {
                            // аватар с инициалами
                            ZStack {
                                Circle().fill(
                                    LinearGradient(colors: [.indigo, .purple],
                                                   startPoint: .top, endPoint: .bottom))
                                Text(String(user.name.prefix(1)).uppercased())
                                    .font(.title.bold())
                                    .foregroundStyle(.white)
                            }
                            .frame(width: 64, height: 64)
                            VStack(alignment: .leading, spacing: 4) {
                                Text(user.name).font(.title3.bold())
                                Text(user.email)
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .padding(.vertical, 4)
                    }
                    Section("Информация") {
                        LabeledContent("Роль", value: roleTitle(user.role))
                        LabeledContent("Рейтинг риска", value:
                            String(format: "%.0f", user.riskScore))
                    }
                }
                Section {
                    Button(role: .destructive) { auth.logout() } label: {
                        Label("Выйти", systemImage: "rectangle.portrait.and.arrow.right")
                    }
                }
            }
            .navigationTitle("Профиль")
            .task {
                await auth.loadMe()
                await loadBalance()
            }
        }
    }

    @State private var topupAmount = 1000

    private func loadBalance() async {
        if let dto: WalletBalanceDTO = try? await APIClient.shared.request(
            "GET", "payments/balance", as: WalletBalanceDTO.self) {
            balance = dto
        }
    }

    private func topup() async {
        isToppingUp = true
        defer { isToppingUp = false }
        do {
            let dto: WalletBalanceDTO = try await APIClient.shared.request(
                "POST", "payments/topup",
                body: ["amount": AnyEncodable(topupAmount)],
                as: WalletBalanceDTO.self)
            balance = dto
            topupError = nil
        } catch {
            topupError = (error as? LocalizedError)?.errorDescription ?? "Не удалось пополнить"
        }
    }

    private func roleTitle(_ role: String) -> String {
        switch role {
        case "ADMIN": return "Администратор"
        case "ORGANIZER": return "Организатор"
        default: return "Пользователь"
        }
    }
}
