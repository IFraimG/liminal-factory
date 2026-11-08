import sys
if __name__=='__main__':
    if sys.argv[1:2]==['--antigravity-client-bridge']:
        from backend.integrations.client_bridge import main
        main(sys.argv[2:])
    else:
        from backend.main import main
        main()
