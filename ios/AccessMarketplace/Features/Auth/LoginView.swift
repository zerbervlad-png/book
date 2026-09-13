// LoginView.swift — auth screens.
import SwiftUI

struct LoginView: View {
    @EnvironmentObject var auth: AuthManager
    @State private var mode: Mode = .login
    @State private var email = ""
    @State private var password = ""
    @State private var name = ""
    @State private var busy = false

    enum Mode: String, CaseIterable { case login = "Sign in", register = "Create account" }

    var body: some View {
        NavigationStack {
            Form {
                Section("Universal Access Marketplace") {
                    if mode == .register {
                        TextField("Name", text: $name)
                            .textInputAutocapitalization(.words)
                    }
                    TextField("Email", text: $email)
                        .keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    SecureField("Password", text: $password)
                }
                Section {
                    Button(mode.rawValue) {
                        Task {
                            busy = true
                            defer { busy = false }
                            switch mode {
                            case .login: await auth.login(email: email, password: password)
                            case .register:
                                await auth.register(email: email, password: password, name: name)
                            }
                        }
                    }
                    .disabled(busy || email.isEmpty || password.count < 8)
                    Picker("Mode", selection: $mode) {
                        ForEach(Mode.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                    }
                    .pickerStyle(.segmented)
                }
                if let error = auth.error {
                    Text(error).foregroundStyle(.red).font(.footnote)
                }
            }
            .navigationTitle("Welcome")
        }
    }
}

struct ProfileView: View {
    @EnvironmentObject var auth: AuthManager

    var body: some View {
        NavigationStack {
            List {
                if let user = auth.user {
                    LabeledContent("Name", value: user.name)
                    LabeledContent("Email", value: user.email)
                    LabeledContent("Role", value: user.role)
                }
                Button("Sign out", role: .destructive) { auth.logout() }
            }
            .navigationTitle("Profile")
            .task { await auth.loadMe() }
        }
    }
}
