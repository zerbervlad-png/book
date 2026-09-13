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
                                .font(.system(size: 72))
                                .foregroundStyle(.white)
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
                                    .fill(.red.opacity(0.35)))
                        }

                        // тестовый аккаунт
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

    var body: some View {
        NavigationStack {
            List {
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
            .task { await auth.loadMe() }
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
